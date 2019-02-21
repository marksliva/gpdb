import os
import signal
import time

from gppylib.mainUtils import *

from gppylib.utils import checkNotNone, appendNewEntriesToHbaFile
from gppylib.db import dbconn
from gppylib import gparray, gplog
from gppylib.commands import unix
from gppylib.commands import gp
from gppylib.commands import base
from gppylib.gparray import GpArray
from gppylib.operations import startSegments
from gppylib.gp_era import read_era
from gppylib.operations.utils import ParallelOperation, RemoteOperation
from gppylib.operations.unix import CleanSharedMem
from gppylib.commands.gp import is_pid_postmaster, get_pid_from_remotehost
from gppylib.commands.unix import check_pid_on_remotehost, Scp
import datetime

logger = gplog.get_default_logger()

gDatabaseDirectories = [
    # this list occur inside initdb.c
    "global",
    "pg_log",
    "pg_xlog",
    "pg_clog",
    "pg_changetracking",
    "pg_subtrans",
    "pg_twophase",
    "pg_multixact",
    "pg_distributedxidmap",
    "pg_distributedlog",
    "pg_utilitymodedtmredo",
    "base",
    "pg_tblspc",
    "pg_stat_tmp"
]

#
# Database files that may exist in the root directory and need deleting 
#
gDatabaseFiles = [
    "PG_VERSION",
    "pg_hba.conf",
    "pg_ident.conf",
    "postgresql.conf",
    "postmaster.log",
    "postmaster.opts",
    "postmaster.pid",
]


#
# note: it's a little quirky that caller must set up failed/failover so that failover is in gparray but
#                                 failed is not (if both set)...change that, or at least protect against problems
#

class GpMirrorToBuild:
    def __init__(self, failedSegment, liveSegment, failoverSegment, forceFullSynchronization, logger=logger):
        checkNotNone("liveSegment", liveSegment)
        checkNotNone("forceFullSynchronization", forceFullSynchronization)

        if failedSegment is None and failoverSegment is None:
            raise Exception("No mirror passed to GpMirrorToBuild")

        if not liveSegment.isSegmentQE():
            raise ExceptionNoStackTraceNeeded("Segment to recover from for content %s is not a correct segment "
                                              "(it is a master or standby master)" % liveSegment.getSegmentContentId())
        if not liveSegment.isSegmentPrimary(True):
            raise ExceptionNoStackTraceNeeded(
                "Segment to recover from for content %s is not a primary" % liveSegment.getSegmentContentId())
        if not liveSegment.isSegmentUp():
            raise ExceptionNoStackTraceNeeded(
                "Primary segment is not up for content %s" % liveSegment.getSegmentContentId())

        if failedSegment is not None:
            if failedSegment.getSegmentContentId() != liveSegment.getSegmentContentId():
                raise ExceptionNoStackTraceNeeded(
                    "The primary is not of the same content as the failed mirror.  Primary content %d, "
                    "mirror content %d" % (liveSegment.getSegmentContentId(), failedSegment.getSegmentContentId()))
            if failedSegment.getSegmentDbId() == liveSegment.getSegmentDbId():
                raise ExceptionNoStackTraceNeeded("For content %d, the dbid values are the same.  "
                                                  "A segment may not be recovered from itself" %
                                                  liveSegment.getSegmentDbId())

        if failoverSegment is not None:
            if failoverSegment.getSegmentContentId() != liveSegment.getSegmentContentId():
                raise ExceptionNoStackTraceNeeded(
                    "The primary is not of the same content as the mirror.  Primary content %d, "
                    "mirror content %d" % (liveSegment.getSegmentContentId(), failoverSegment.getSegmentContentId()))
            if failoverSegment.getSegmentDbId() == liveSegment.getSegmentDbId():
                raise ExceptionNoStackTraceNeeded("For content %d, the dbid values are the same.  "
                                                  "A segment may not be built from itself"
                                                  % liveSegment.getSegmentDbId())

        if failedSegment is not None and failoverSegment is not None:
            # for now, we require the code to have produced this -- even when moving the segment to another
            #  location, we preserve the directory
            assert failedSegment.getSegmentDbId() == failoverSegment.getSegmentDbId()

        self.__failedSegment = failedSegment
        self.__liveSegment = liveSegment
        self.__failoverSegment = failoverSegment

        """
        __forceFullSynchronization is true if full resynchronization should be FORCED -- that is, the
           existing segment will be cleared and all objects will be transferred by the file resynchronization
           process on the server
        """
        self.__forceFullSynchronization = forceFullSynchronization

    def getFailedSegment(self):
        """
        returns the segment that failed. This can be None, for example when adding mirrors
        """
        return self.__failedSegment

    def getLiveSegment(self):
        """
        returns the primary segment from which the recovery will take place.  Will always be non-None
        """
        return self.__liveSegment

    def getFailoverSegment(self):
        """
        returns the target segment to which we will copy the data, or None
            if we will recover in place.  Note that __failoverSegment should refer to the same dbid
            as __failedSegment, but should have updated path + file information.
        """
        return self.__failoverSegment

    def isFullSynchronization(self):
        """
        Returns whether or not this segment to recover needs to recover using full resynchronization
        """

        if self.__forceFullSynchronization:
            return True

        # if we are failing over to a new segment location then we must fully resync
        if self.__failoverSegment is not None:
            return True

        return False


class GpMirrorListToBuild:
    def __init__(self, toBuild, pool, quiet, parallelDegree, additionalWarnings=None, logger=logger, forceoverwrite=False):
        self.__mirrorsToBuild = toBuild
        self.__pool = pool
        self.__quiet = quiet
        self.__parallelDegree = parallelDegree
        self.__forceoverwrite = forceoverwrite
        self.__additionalWarnings = additionalWarnings or []
        if not logger:
            raise Exception('logger argument cannot be None')

        self.__logger = logger

    def getMirrorsToBuild(self):
        """
        Returns a newly allocated list
        """
        return [m for m in self.__mirrorsToBuild]

    def getAdditionalWarnings(self):
        """
        Returns any additional warnings generated during building of list
        """
        return self.__additionalWarnings

    def buildMirrors(self, actionName, gpEnv, gpArray):
        """
        Build the mirrors.

        gpArray must have already been altered to have updated directories -- that is, the failoverSegments
            from the mirrorsToBuild must be present in gpArray.

        """

        if len(self.__mirrorsToBuild) == 0:
            self.__logger.info("No segments to " + actionName)
            return True

        self.checkForPortAndDirectoryConflicts(gpArray)

        self.__logger.info("%s segment(s) to %s" % (len(self.__mirrorsToBuild), actionName))

        # make sure the target directories are up-to-date
        #  by cleaning them, if needed, and then copying a basic directory there
        #  the postgresql.conf in that basic directory will need updating (to change the port)
        toStopDirectives = []
        toEnsureMarkedDown = []
        cleanupDirectives = []
        copyDirectives = []
        for toRecover in self.__mirrorsToBuild:

            if toRecover.getFailedSegment() is not None:
                # will stop the failed segment.  Note that we do this even if we are recovering to a different location!
                toStopDirectives.append(GpStopSegmentDirectoryDirective(toRecover.getFailedSegment()))
                if toRecover.getFailedSegment().getSegmentStatus() == gparray.STATUS_UP:
                    toEnsureMarkedDown.append(toRecover.getFailedSegment())

            if toRecover.isFullSynchronization():

                isTargetReusedLocation = False
                if toRecover.getFailedSegment() is not None and \
                                toRecover.getFailoverSegment() is None:
                    #
                    # We are recovering a failed segment in-place
                    #
                    cleanupDirectives.append(GpCleanupSegmentDirectoryDirective(toRecover.getFailedSegment()))
                    isTargetReusedLocation = True

                if toRecover.getFailoverSegment() is not None:
                    targetSegment = toRecover.getFailoverSegment()
                else:
                    targetSegment = toRecover.getFailedSegment()

                d = GpCopySegmentDirectoryDirective(toRecover.getLiveSegment(), targetSegment, isTargetReusedLocation)
                copyDirectives.append(d)

        self.__ensureStopped(gpEnv, toStopDirectives)
        self.__ensureSharedMemCleaned(gpEnv, toStopDirectives)
        self.__ensureMarkedDown(gpEnv, toEnsureMarkedDown)
        if not self.__forceoverwrite:
            self.__cleanUpSegmentDirectories(cleanupDirectives)
        self.__copySegmentDirectories(gpEnv, gpArray, copyDirectives)

        # update and save metadata in memory
        for toRecover in self.__mirrorsToBuild:

            if toRecover.getFailoverSegment() is None:
                # we are recovering the lost segment in place
                seg = toRecover.getFailedSegment()
            else:
                seg = toRecover.getFailedSegment()
                # no need to update the failed segment's information -- it is
                #   being overwritten in the configuration with the failover segment
                for gpArraySegment in gpArray.getDbList():
                    if gpArraySegment is seg:
                        raise Exception(
                            "failed segment should not be in the new configuration if failing over to new segment")

                seg = toRecover.getFailoverSegment()
            seg.setSegmentStatus(gparray.STATUS_DOWN)  # down initially, we haven't started it yet
            seg.setSegmentMode(gparray.MODE_NOT_SYNC)

        # figure out what needs to be started or transitioned
        mirrorsToStart = []
        rewindInfo = []
        primariesToConvert = []
        convertPrimaryUsingFullResync = []
        fullResyncMirrorDbIds = {}
        for toRecover in self.__mirrorsToBuild:
            seg = toRecover.getFailoverSegment()
            if seg is None:
                seg = toRecover.getFailedSegment()  # we are recovering in place
            mirrorsToStart.append(seg)
            primarySeg = toRecover.getLiveSegment()

            # Append to rewindInfo to execute pg_rewind later if we are not
            # using full recovery. We will run pg_rewind on incremental recovery
            # if the target mirror does not have recovery.conf file because
            # segment failover happened. The check for recovery.conf file will
            # happen in the same remote SegmentRewind Command call.
            if not toRecover.isFullSynchronization() \
               and seg.getSegmentRole() == gparray.ROLE_MIRROR:
                rewindInfo.append((seg, primarySeg.getSegmentHostName(), primarySeg.getSegmentPort()))

            # The change in configuration to of the mirror to down requires that
            # the primary also be marked as unsynchronized.
            primarySeg.setSegmentMode(gparray.MODE_NOT_SYNC)
            primariesToConvert.append(primarySeg)
            convertPrimaryUsingFullResync.append(toRecover.isFullSynchronization())

            if toRecover.isFullSynchronization() and seg.getSegmentDbId() > 0:
                fullResyncMirrorDbIds[seg.getSegmentDbId()] = True

        # should use mainUtils.getProgramName but I can't make it work!
        programName = os.path.split(sys.argv[0])[-1]

        # Disable Ctrl-C, going to save metadata in database and transition segments
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            self.__logger.info("Updating mirrors")

            if actionName ==  "add":
                self.__registerMirrorsInCatalog(gpArray)

            if len(rewindInfo) != 0:
                self.__logger.info("Running pg_rewind on required mirrors")
                rewindFailedSegments = self.run_pg_rewind(rewindInfo)

                # Do not start mirrors that failed pg_rewind
                for failedSegment in rewindFailedSegments:
                    mirrorsToStart.remove(failedSegment)

            self.__logger.info("Starting mirrors")
            start_all_successful = self.__startAll(gpEnv, gpArray, mirrorsToStart)
        finally:
            # Reenable Ctrl-C
            signal.signal(signal.SIGINT, signal.default_int_handler)

        return start_all_successful

    def run_pg_rewind(self, rewindInfo):
        """
        Run pg_rewind for incremental recovery.
        """

        rewindFailedSegments = []
        # Run pg_rewind on all the targets
        for targetSegment, sourceHostName, sourcePort in rewindInfo:
            # Do CHECKPOINT on source to force TimeLineID to be updated in pg_control.
            # pg_rewind wants that to make incremental recovery successful finally.
            self.__logger.debug('Do CHECKPOINT on %s (port: %d) before running pg_rewind.' % (sourceHostName, sourcePort))
            dburl = dbconn.DbURL(hostname=sourceHostName,
                                 port=sourcePort,
                                 dbname='template1')
            conn = dbconn.connect(dburl, utility=True)
            dbconn.execSQL(conn, "CHECKPOINT")

            # If the postmaster.pid still exists and another process
            # is actively using that pid, pg_rewind will fail when it
            # tries to start the failed segment in single-user
            # mode. It should be safe to remove the postmaster.pid
            # file since we do not expect the failed segment to be up.
            self.remove_postmaster_pid_from_remotehost(
                targetSegment.getSegmentHostName(),
                targetSegment.getSegmentDataDirectory())

            # Run pg_rewind to do incremental recovery.
            cmd = gp.SegmentRewind('segment rewind',
                                   targetSegment.getSegmentHostName(),
                                   targetSegment.getSegmentDataDirectory(),
                                   sourceHostName,
                                   sourcePort,
                                   verbose=gplog.logging_is_verbose())
            try:
                cmd.run(True)
                self.__logger.debug('pg_rewind results: %s' % cmd.results)
            except base.ExecutionError as e:
                self.__logger.debug("pg_rewind failed for target directory %s." % targetSegment.getSegmentDataDirectory())
                self.__logger.warning("Incremental recovery failed for dbid %s. You must use gprecoverseg -F to recover the segment." % targetSegment.getSegmentDbId())
                rewindFailedSegments.append(targetSegment)

        return rewindFailedSegments

    def remove_postmaster_pid_from_remotehost(self, host, datadir):
        cmd = base.Command(name = 'remove the postmaster.pid file',
                           cmdStr = 'rm -f %s/postmaster.pid' % datadir,
                           ctxt=gp.REMOTE, remoteHost = host)
        cmd.run()

        return_code = cmd.get_return_code()
        if return_code != 0:
            raise ExecutionError("Failed while trying to remove postmaster.pid.", cmd)

    def checkForPortAndDirectoryConflicts(self, gpArray):
        """
        Check gpArray for internal consistency -- no duplicate ports or directories on the same host, for example

        A detected problem causes an Exception to be raised
        """

        for hostName, segmentArr in GpArray.getSegmentsByHostName(gpArray.getDbList()).iteritems():
            usedPorts = {}
            usedDataDirectories = {}
            for segment in segmentArr:

                # check for port conflict
                port = segment.getSegmentPort()
                dbid = segment.getSegmentDbId()
                if port in usedPorts:
                    raise Exception(
                        "On host %s, port %s for segment with dbid %s conflicts with port for segment dbid %s" %
                        (hostName, port, dbid, usedPorts.get(port)))

                usedPorts[port] = dbid

                # check for directory conflict; could improve this by reporting nicer the conflicts
                path = segment.getSegmentDataDirectory()

                if path in usedDataDirectories:
                    raise Exception(
                        "On host %s, data directory for segment with dbid %s conflicts with "
                        "data directory for segment dbid %s; directory: %s" %
                        (hostName, dbid, usedDataDirectories.get(path), path))
                usedDataDirectories[path] = dbid

    def __runWaitAndCheckWorkerPoolForErrorsAndClear(self, cmds, actionVerb, suppressErrorCheck=False, log_files=[]):
        for cmd in cmds:
            self.__pool.addCommand(cmd)

        if self.__quiet:
            self.__pool.join()
        else:
            if log_files:
                base.join_and_indicate_log_files_progress(self.__pool, log_files)
            else:
                base.join_and_indicate_progress(self.__pool)

        if not suppressErrorCheck:
            self.__pool.check_results()
        self.__pool.empty_completed_items()

    def __copyFiles(self, srcDir, destDir, fileNames):
        for name in fileNames:
            cmd = gp.LocalCopy("copy file for segment", srcDir + "/" + name, destDir + "/" + name)
            cmd.run(validateAfter=True)

    def __createEmptyDirectories(self, dir, newDirectoryNames):
        for name in newDirectoryNames:
            subDir = os.path.join(dir, name)
            unix.MakeDirectory("create blank directory for segment", subDir).run(validateAfter=True)
            unix.Chmod.local('set permissions on blank dir', subDir, '0700')

    def __copySegmentDirectories(self, gpEnv, gpArray, directives):
        """
        directives should be composed of GpCopySegmentDirectoryDirective values
        """
        if len(directives) == 0:
            return

        srcSegments = []
        destSegments = []
        isTargetReusedLocation = []
        for directive in directives:
            srcSegment = directive.getSrcSegment()
            destSegment = directive.getDestSegment()
            destSegment.primaryHostname = srcSegment.getSegmentHostName()
            destSegment.primarySegmentPort = srcSegment.getSegmentPort()

            srcSegments.append(srcSegment)
            destSegments.append(destSegment)
            isTargetReusedLocation.append(directive.isTargetReusedLocation())

        destSegmentByHost = GpArray.getSegmentsByHostName(destSegments)
        newSegmentInfo = gp.ConfigureNewSegment.buildSegmentInfoForNewSegment(destSegments, isTargetReusedLocation)
        i = 0

        def createConfigureNewSegmentCommand(hostName, cmdLabel, validationOnly, log_files, i):

            segmentInfo = newSegmentInfo[hostName]
            checkNotNone("segmentInfo for %s" % hostName, segmentInfo)

            pgbasebackup_start_time = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')
            log_file = '%s/pg_basebackup.%s.dbid%s.out' % (gplog.get_logger_dir(),
                                                                                  pgbasebackup_start_time,
                                                                                  i) # todo fix it
            i += 1
            log_files.append({
                'log_file': log_file,
                'host_name': hostName
            })

            return gp.ConfigureNewSegment(cmdLabel,
                                          segmentInfo,
                                          log_file,
                                          newSegments=True,
                                          verbose=gplog.logging_is_verbose(),
                                          batchSize=self.__parallelDegree,
                                          ctxt=gp.REMOTE,
                                          remoteHost=hostName,
                                          validationOnly=validationOnly,
                                          forceoverwrite=self.__forceoverwrite)

        #
        # validate directories for target segments
        #
        self.__logger.info('Validating remote directories')
        cmds = []
        log_files = []
        for hostName in destSegmentByHost.keys():
            cmds.append(createConfigureNewSegmentCommand(hostName, 'validate blank segments', True, log_files, i))
        for cmd in cmds:
            self.__pool.addCommand(cmd)

        if self.__quiet:
            self.__pool.join()
        else:
            base.join_and_indicate_log_files_progress(self.__pool, log_files)

        validationErrors = []
        for item in self.__pool.getCompletedItems():
            results = item.get_results()
            if not results.wasSuccessful():
                if results.rc == 1:
                    # stdoutFromFailure = results.stdout.replace("\n", " ").strip()
                    lines = results.stderr.split("\n")
                    for line in lines:
                        if len(line.strip()) > 0:
                            validationErrors.append("Validation failure on host %s %s" % (item.remoteHost, line))
                else:
                    validationErrors.append(str(item))
        self.__pool.empty_completed_items()
        if validationErrors:
            raise ExceptionNoStackTraceNeeded("\n" + ("\n".join(validationErrors)))

        #
        # unpack and configure new segments
        #
        self.__logger.info('Configuring new segments')
        cmds = []
        for hostName in destSegmentByHost.keys():
            cmds.append(createConfigureNewSegmentCommand(hostName, 'configure blank segments', False, log_files, i))
        self.__runWaitAndCheckWorkerPoolForErrorsAndClear(cmds, "unpacking basic segment directory", suppressErrorCheck=False, log_files=log_files)

        #
        # copy dump files from old segment to new segment
        #
        for srcSeg in srcSegments:
            for destSeg in destSegments:
                if srcSeg.content == destSeg.content:
                    src_dump_dir = os.path.join(srcSeg.getSegmentDataDirectory(), 'db_dumps')
                    cmd = base.Command('check existence of db_dumps directory', 'ls %s' % (src_dump_dir),
                                       ctxt=base.REMOTE, remoteHost=destSeg.getSegmentAddress())
                    cmd.run()
                    if cmd.results.rc == 0:  # Only try to copy directory if it exists
                        cmd = Scp('copy db_dumps from old segment to new segment',
                                  os.path.join(srcSeg.getSegmentDataDirectory(), 'db_dumps*', '*'),
                                  os.path.join(destSeg.getSegmentDataDirectory(), 'db_dumps'),
                                  srcSeg.getSegmentAddress(),
                                  destSeg.getSegmentAddress(),
                                  recursive=True)
                        cmd.run(validateAfter=True)
                        break

    def _get_running_postgres_segments(self, segments):
        running_segments = []
        for seg in segments:
            datadir = self.dereference_remote_symlink(seg.getSegmentDataDirectory(), seg.getSegmentHostName())
            pid = get_pid_from_remotehost(seg.getSegmentHostName(), datadir)
            if pid is not None:
                if check_pid_on_remotehost(pid, seg.getSegmentHostName()):
                    if is_pid_postmaster(datadir, pid, seg.getSegmentHostName()):
                        running_segments.append(seg)
                    else:
                        self.__logger.info("Skipping to stop segment %s on host %s since it is not a postgres process" % (
                        seg.getSegmentDataDirectory(), seg.getSegmentHostName()))
                else:
                    self.__logger.debug("Skipping to stop segment %s on host %s since process with pid %s is not running" % (
                    seg.getSegmentDataDirectory(), seg.getSegmentHostName(), pid))
            else:
                self.__logger.debug("Skipping to stop segment %s on host %s since pid could not be found" % (
                seg.getSegmentDataDirectory(), seg.getSegmentHostName()))

        return running_segments

    def dereference_remote_symlink(self, datadir, host):
        cmdStr = """python -c 'import os; print os.path.realpath("%s")'""" % datadir
        cmd = base.Command('dereference a symlink on a remote host', cmdStr=cmdStr, ctxt=base.REMOTE, remoteHost=host)
        cmd.run()
        results = cmd.get_results()
        if results.rc != 0:
            self.__logger.warning('Unable to determine if %s is symlink. Assuming it is not symlink' % (datadir))
            return datadir
        return results.stdout.strip()

    def __ensureSharedMemCleaned(self, gpEnv, directives):
        """

        @param directives a list of the GpStopSegmentDirectoryDirective values indicating which segments to cleanup 

        """

        if len(directives) == 0:
            return

        self.__logger.info('Ensuring that shared memory is cleaned up for stopped segments')
        segments = [d.getSegment() for d in directives]
        segmentsByHost = GpArray.getSegmentsByHostName(segments)
        operation_list = [RemoteOperation(CleanSharedMem(segments), host=hostName) for hostName, segments in
                          segmentsByHost.items()]
        ParallelOperation(operation_list).run()

        for operation in operation_list:
            try:
                operation.get_ret()
            except Exception as e:
                self.__logger.warning('Unable to clean up shared memory for stopped segments on host (%s)' % operation.host)

    def __ensureStopped(self, gpEnv, directives):
        """

        @param directives a list of the GpStopSegmentDirectoryDirective values indicating which segments to stop

        """
        if len(directives) == 0:
            return

        self.__logger.info("Ensuring %d failed segment(s) are stopped" % (len(directives)))
        segments = [d.getSegment() for d in directives]
        segments = self._get_running_postgres_segments(segments)
        segmentByHost = GpArray.getSegmentsByHostName(segments)

        cmds = []
        for hostName, segments in segmentByHost.iteritems():
            cmd = gp.GpSegStopCmd("remote segment stop on host '%s'" % hostName,
                                  gpEnv.getGpHome(), gpEnv.getGpVersion(),
                                  mode='fast', dbs=segments, verbose=gplog.logging_is_verbose(),
                                  ctxt=base.REMOTE, remoteHost=hostName)

            cmds.append(cmd)

        # we suppress checking for the error.  This is because gpsegstop will actually error
        #  in many cases where the stop is actually done (that is, for example, the segment is
        #  running but slow to shutdown so gpsegstop errors after whacking it with a kill)
        #
        # Perhaps we should make it so that it so that is checks if the seg is running and only attempt stop
        #  if it's running?  In that case, we could propagate the error
        #
        self.__runWaitAndCheckWorkerPoolForErrorsAndClear(cmds, "stopping segments", suppressErrorCheck=True)

    def __ensureMarkedDown(self, gpEnv, toEnsureMarkedDown):
        """Waits for FTS prober to mark segments as down"""

        wait_time = 60 * 30  # Wait up to 30 minutes to handle very large, busy
        # clusters that may have faults.  In most cases the
        # actual time to wait will be small and this operation
        # is only needed when moving mirrors that are up and
        # needed to be stopped, an uncommon operation.

        dburl = dbconn.DbURL(port=gpEnv.getMasterPort(), dbname='template1')

        time_elapsed = 0
        seg_up_count = 0
        initial_seg_up_count = len(toEnsureMarkedDown)
        last_seg_up_count = initial_seg_up_count

        if initial_seg_up_count == 0:
            # Nothing to wait on
            return

        self.__logger.info("Waiting for segments to be marked down.")
        self.__logger.info("This may take up to %d seconds on large clusters." % wait_time)

        # wait for all needed segments to be marked down by the prober.  We'll wait
        # a max time of double the interval 
        while wait_time > time_elapsed:
            seg_up_count = 0
            current_gparray = GpArray.initFromCatalog(dburl, True)
            seg_db_map = current_gparray.getSegDbMap()

            # go through and get the status of each segment we need to be marked down
            for segdb in toEnsureMarkedDown:
                if segdb.getSegmentDbId() in seg_db_map and seg_db_map[segdb.getSegmentDbId()].isSegmentUp():
                    seg_up_count += 1
            if seg_up_count == 0:
                break
            else:
                if last_seg_up_count != seg_up_count:
                    print "\n",
                    self.__logger.info("%d of %d segments have been marked down." %
                                (initial_seg_up_count - seg_up_count, initial_seg_up_count))
                    last_seg_up_count = seg_up_count

                for _i in range(1, 5):
                    time.sleep(1)
                    sys.stdout.write(".")
                    sys.stdout.flush()

                time_elapsed += 5

        if seg_up_count == 0:
            print "\n",
            self.__logger.info("%d of %d segments have been marked down." %
                        (initial_seg_up_count, initial_seg_up_count))
        else:
            raise Exception("%d segments were not marked down by FTS" % seg_up_count)

    def __cleanUpSegmentDirectories(self, directives):
        if len(directives) == 0:
            return

        self.__logger.info("Cleaning files from %d segment(s)" % (len(directives)))
        segments = [d.getSegment() for d in directives]
        segmentByHost = GpArray.getSegmentsByHostName(segments)

        cmds = []
        for hostName, segments in segmentByHost.iteritems():
            cmds.append(gp.GpCleanSegmentDirectories("clean segment directories on %s" % hostName,
                                                     segments, gp.REMOTE, hostName))

        self.__runWaitAndCheckWorkerPoolForErrorsAndClear(cmds, "cleaning existing directories")

    def __createStartSegmentsOp(self, gpEnv):
        return startSegments.StartSegmentsOperation(self.__pool, self.__quiet,
                                                    gpEnv.getGpVersion(),
                                                    gpEnv.getGpHome(), gpEnv.getMasterDataDir()
                                                    )

    def __registerMirrorsInCatalog(self, gpArray):
        self.__logger.info("Updating gp_segment_configuration with mirror info")
        dburl = dbconn.DbURL(dbname='template1', port=gpArray.master.port)
        conn = dbconn.connect(dburl, utility=False)
        query = "select pg_catalog.gp_add_segment_mirror(%s::int2, '%s', '%s', %s, '%s');"

        try:
            for segmentPair in gpArray.getSegmentList():
                mirror = segmentPair.mirrorDB
                filledInQuery = query % (mirror.getSegmentContentId(), mirror.getSegmentAddress(),
                                         mirror.getSegmentAddress(), mirror.getSegmentPort(), mirror.getSegmentDataDirectory())
                dbconn.execSQL(conn, filledInQuery)

        except Exception as e:
            self.__logger.error("Failed while updating mirror info in gp_segment_configuration: %s" % str(e))
            raise

        else:
            conn.commit()
            self.__logger.info("Successfully updated gp_segment_configuration with mirror info")

    def __updateGpIdFile(self, gpEnv, gpArray, segments):
        segmentByHost = GpArray.getSegmentsByHostName(segments)
        newSegmentInfo = gp.ConfigureNewSegment.buildSegmentInfoForNewSegment(segments)

        cmds = []
        for hostName in segmentByHost.keys():
            segmentInfo = newSegmentInfo[hostName]
            checkNotNone("segmentInfo for %s" % hostName, segmentInfo)
            cmd = gp.ConfigureNewSegment("update gpid file",
                                         segmentInfo,
                                         '%s/%s' % (gplog.get_logger_dir(), 'a-filepath'), # todo needs to be a real filepath. also is this method used anywhere?
                                         newSegments=False,
                                         verbose=gplog.logging_is_verbose(),
                                         batchSize=self.__parallelDegree,
                                         ctxt=gp.REMOTE,
                                         remoteHost=hostName,
                                         validationOnly=False,
                                         writeGpIdFileOnly=True)

            cmds.append(cmd)
        self.__runWaitAndCheckWorkerPoolForErrorsAndClear(cmds, "writing updated gpid files")

    def __startAll(self, gpEnv, gpArray, segments):

        # the newly started segments should belong to the current era
        era = read_era(gpEnv.getMasterDataDir(), logger=self.__logger)

        segmentStartResult = self.__createStartSegmentsOp(gpEnv).startSegments(gpArray, segments,
                                                                               startSegments.START_AS_MIRRORLESS,
                                                                               era)
        start_all_successfull = len(segmentStartResult.getFailedSegmentObjs()) == 0
        for failure in segmentStartResult.getFailedSegmentObjs():
            failedSeg = failure.getSegment()
            failureReason = failure.getReason()
            self.__logger.warn(
                "Failed to start segment.  The fault prober will shortly mark it as down. Segment: %s: REASON: %s" % (
                failedSeg, failureReason))

        return start_all_successfull

class GpCleanupSegmentDirectoryDirective:
    def __init__(self, segment):
        checkNotNone("segment", segment)
        self.__segment = segment

    def getSegment(self):
        return self.__segment


class GpStopSegmentDirectoryDirective:
    def __init__(self, segment):
        checkNotNone("segment", segment)
        self.__segment = segment

    def getSegment(self):
        return self.__segment


class GpCopySegmentDirectoryDirective:
    def __init__(self, source, dest, isTargetReusedLocation):
        """
        @param isTargetReusedLocation if True then the dest location is a cleaned-up location
        """
        checkNotNone("source", source)
        checkNotNone("dest", dest)

        self.__source = source
        self.__dest = dest
        self.__isTargetReusedLocation = isTargetReusedLocation

    def getSrcSegment(self):
        return self.__source

    def getDestSegment(self):
        return self.__dest

    def isTargetReusedLocation(self):
        return self.__isTargetReusedLocation

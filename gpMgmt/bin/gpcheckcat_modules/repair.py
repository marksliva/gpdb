#!/usr/bin/env python
"""
Purpose : Creates the repair dir and the corresponding sql/bash scripts for
          repairing some of the catalog issues(see the list below) reported by gpcheckcat.
          Not responsible for generating the repair contents.

Creates repair for the following gpcheckcat checks
       * missing_extraneous
       * owner
       * part_integrity
       * distribution_policy
"""

import os
import stat
from gpcheckcat_modules.repair_missing_extraneous import RepairMissingExtraneous


class Repair:
    def __init__(self, context=None, issue_type=None, desc=None):
        self._context = context
        self._issue_type = issue_type
        self._desc = desc

    def create_repair(self, sql_repair_contents):
        repair_dir = self.create_repair_dir()

        master_segment, = filter(lambda config: config['content'] == -1, self._context.cfg.values())

        sql_filename = self.__create_sql_file_in_repair_dir(repair_dir, sql_repair_contents, master_segment)
        self.__create_bash_script_in_repair_dir(repair_dir, sql_filename, master_segment)

        return repair_dir

    def create_repair_for_extra_missing(self, catalog_table_obj, issues, pk_name, segments):
        catalog_name = catalog_table_obj.getTableName()
        extra_missing_repair_obj = RepairMissingExtraneous(catalog_table_obj=catalog_table_obj,
                                                           issues=issues,
                                                           pk_name=pk_name)
        repair_dir = self.create_repair_dir()
        segment_to_oids_map = extra_missing_repair_obj.get_segment_to_oid_mapping(map(lambda config: config['content'], segments.values()))

        for segment_id, oids in segment_to_oids_map.iteritems():
            segment, = filter(lambda config: config['content'] == segment_id, segments.values())

            sql_content = extra_missing_repair_obj.get_delete_sql(oids)
            self.__create_bash_script_in_repair_dir(repair_dir, sql_content,
                                                    segment=segment, catalog_name=catalog_name)

        return repair_dir

    def create_segment_repair_scripts(self, segments):
        repair_dir = self.create_repair_dir()

        for segment in segments:
            sql_filename = self.__create_sql_file_in_repair_dir(repair_dir, segment['repair_statements'], segment)
            self.__create_bash_script_in_repair_dir(repair_dir, sql_filename, segment)

        return repair_dir

    def create_repair_dir(self):
        repair_dir = self._context.opt['-g']
        if not os.path.exists(repair_dir):
            os.mkdir(repair_dir)

        return repair_dir

    def append_content_to_bash_script(self, repair_dir_path, script, catalog_name=None):
        bash_file_path = self.__get_bash_filepath(repair_dir_path, catalog_name)
        if not os.path.isfile(bash_file_path):
            script = '#!/bin/bash\ncd $(dirname $0)\n' + script

        with open(bash_file_path, 'a') as bash_file:
            bash_file.write(script)

        os.chmod(bash_file_path, stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)

    def __create_sql_file_in_repair_dir(self, repair_dir, sql_repair_contents, segment):
        sql_filename = self.__get_filename(segment) + ".sql"
        sql_file_path = os.path.join(repair_dir, sql_filename)

        with open(sql_file_path, 'w') as sql_file:
            for content in sql_repair_contents:
                sql_file.write(content + "\n")

        return sql_filename

    def __create_bash_script_in_repair_dir(self, repair_dir, sql_filename, segment, catalog_name=None):
        if not sql_filename:
            return

        bash_script_content = self.__get_bash_script_content(sql_filename, segment)
        self.append_content_to_bash_script(repair_dir, bash_script_content, catalog_name)

    def __get_filename(self, segment):
        if segment['content'] == -1:
            return '%s_%s_%s' % (self._context.dbname, self._issue_type, self._context.timestamp)
        else:
            filename = '%i.%s.%i.%s.%s' % (segment['dbid'], segment['hostname'], segment['port'], self._context.dbname, self._context.timestamp)
            return filename.replace(' ', '_')

    def __get_bash_filepath(self, repair_dir, catalog_name=None):
        bash_filename = 'runsql_%s.sh' % self._context.timestamp

        if self._issue_type and catalog_name:
            bash_filename = 'run_{0}_{1}_{2}_{3}.sh'.format(self._context.dbname, self._issue_type, catalog_name, self._context.timestamp)

        return os.path.join(repair_dir, bash_filename)

    def __get_bash_script_content(self, sql_filename, segment):
        out_filename = self.__get_filename(segment) + ".out"

        bash_script_content = '\necho "{0}"\n'.format(self._desc)
        bash_script_content += self.__get_psql_command(segment, sql_filename, out_filename)
        return bash_script_content

    def __get_psql_command(self, segment, sql_filename, out_filename):
        """
        cases to consider
        self._issue_type : extra/missing vs everything else(policies, owner, constraint)
        master vs segment
        """
        psql_cmd = ""

        if segment['content'] != -1:
            psql_cmd += 'PGOPTIONS=\'-c gp_session_role=utility\' '

        psql_cmd += 'psql -X -a -h {hostname} -p {port} '.format(hostname=segment['hostname'], port=segment['port'])

        if self._issue_type == 'extra' or self._issue_type == 'missing':
            psql_cmd += '-c '
        else:
            psql_cmd += '-f '

        psql_cmd += '"{sql_filename}" "{dbname}" >> {out_filename} 2>&1\n'.format(
            sql_filename=sql_filename,
            dbname=self._context.dbname,
            out_filename=out_filename)
        return psql_cmd

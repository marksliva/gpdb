import os

from behave import given, when, then


# To test that an added mirror/standby works properly, we ensure that we
#   can actually recover data on that segment when it fails over.  We also
#   then bring up the original segment pair to ensure that the new primary/master
#   is fully functional.
# We follow these steps:
# 1). add table/data to current master/primary
# 2). stop master/primary
# 3). wait for automatic failover(for downed primary) or explicitly promote standby(for downed master)
# 4). make sure data is on new master/primary
# -). prepare for 6: recoverseg to bring up old master/primary as standby/mirror
# 6). repeat 1-4 for new-old back to old-new
# NOTE: this method leaves the cluster without a standby-master
@then('the {segment} replicates and fails over and back correctly')
@then('the {segment} replicate and fail over and back correctly')
def impl(context, segment):
    if segment not in ('standby', 'mirrors'):
        raise Exception("")

    context.execute_steps(u"""
    Given the segments are synchronized
      And a tablespace is created with data
    """)

    # For the 'standby' case, we set PGHOST back to its original value instead
    # of 'mdw-1'.  When the function impl() is called, PGHOST is initially unset
    # by the test framework, and we want to respect that.
    # TODO: set it to 'mdw-1' at the end since that's what we want?
    orig_PGHOST = os.environ.get('PGHOST')

    # Fail over to standby/mirrors.
    if segment == 'standby':
        context.execute_steps(u"""
         When the master goes down
          And the user runs command "gpactivatestandby -a" from standby master
         Then gpactivatestandby should return a return code of 0
         """)
        os.environ['PGHOST'] = 'smdw-2'

    else: # mirrors
        context.execute_steps(u"""
        Given user stops all primary processes
          And user can start transactions
         When the user runs "gprecoverseg -a"
         Then gprecoverseg should return a return code of 0
        """)

    context.execute_steps(u"""
     Then the segments are synchronized
      And the tablespace is valid

    Given another tablespace is created with data
    """)

    # Fail over (rebalance) to original master/primaries.
    if segment == 'standby':
        # NOTE: this must be set before gpactivatestandby is called
        if orig_PGHOST is None:
            del os.environ['PGHOST']
        else:
            os.environ['PGHOST'] = orig_PGHOST
        context.execute_steps(u"""
         When running gpinitstandby on host "smdw-2" to create a standby on host "mdw-1"
         Then gpinitstandby should return a return code of 0

         When the master goes down on "smdw-2"
          And the user runs "gpactivatestandby -a"
         Then gpactivatestandby should return a return code of 0
        """)

    else: # mirrors
        context.execute_steps(u"""
         When the user runs "gprecoverseg -ra"
         Then gprecoverseg should return a return code of 0
        """)

    context.execute_steps(u"""
     Then the segments are synchronized
      And the tablespace is valid
      And the other tablespace is valid
    """)

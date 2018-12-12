#!/usr/bin/env python

class OrphanedToastTablesCheck:

    def __init__(self):
        # Normally, there's a "loop" between a table and its TOAST table:
        # - The table's reltoastrelid field in pg_class points to its TOAST table
        # - The TOAST table has an entry in pg_depend pointing to its table
        # This can break and orphan a TOAST table in one of three ways:
        # - The reltoastrelid entry is set to 0
        # - The reltoastrelid entry is set to a different oid value
        # - The pg_depend entry is missing
        # - The reltoastrelid entry is wrong *and* the pg_depend entry is missing
        # The following query attempts to "follow" the loop from pg_class to
        # pg_depend back to pg_class, and if the table oids don't match and/or
        # one is missing, the TOAST table is considered to be an orphan.
        self.orphaned_toast_tables_query = """
SELECT
    array_agg(gp_segment_id),
    toast_table_name,
    expected_table_name,
    dependent_table_name
FROM (
    SELECT
        tst.gp_segment_id,
        tst.relname AS toast_table_name,
        tbl.relname AS expected_table_name,
        dep.refobjid::regclass::text AS dependent_table_name
    FROM
        pg_class tst
        LEFT JOIN pg_depend dep ON tst.oid = dep.objid
        LEFT JOIN pg_class tbl ON tst.oid = tbl.reltoastrelid
    WHERE tst.relkind='t'
        AND	(
            tbl.oid IS NULL
            OR refobjid IS NULL
            OR tbl.oid != dep.refobjid
        )
        AND (
            tbl.relnamespace IS NULL
            OR tbl.relnamespace != (SELECT oid FROM pg_namespace WHERE nspname = 'pg_catalog')
        )
    UNION ALL
    SELECT
        tst.gp_segment_id,
        tst.relname AS toast_table_name,
        tbl.relname AS expected_table_name,
        dep.refobjid::regclass::text AS dependent_table_name
    FROM gp_dist_random('pg_class') tst
        LEFT JOIN pg_depend dep ON tst.oid = dep.objid
        LEFT JOIN pg_class tbl ON tst.oid = tbl.reltoastrelid
    WHERE tst.relkind='t'
        AND (
            tbl.oid IS NULL
            OR refobjid IS NULL
            OR tbl.oid != dep.refobjid
        )
        AND (
            tbl.relnamespace IS NULL
            OR tbl.relnamespace != (SELECT oid FROM pg_namespace WHERE nspname = 'pg_catalog')
        )
    ORDER BY toast_table_name, expected_table_name, dependent_table_name, gp_segment_id
) AS subquery
GROUP BY toast_table_name, expected_table_name, dependent_table_name;
"""

    def runCheck(self, db_connection):
        orphaned_toast_tables = db_connection.query(self.orphaned_toast_tables_query).getresult()
        if len(orphaned_toast_tables) == 0:
            return True, None, None, None

        self.reference_orphans = [] # orphaned by missing reltoastrelid value
        self.dependency_orphans = [] # orphaned by missing pg_depend entry
        self.mismatch_orphans = [] # orphaned by incorrect reltoastrelid value
        self.double_orphans = [] # orphaned by both missing/incorrect reltoastrelid value and missing pg_depend entry

        for (gp_segment_ids, toast_table_name, expected_table_name, dependent_table_name) in orphaned_toast_tables:
            orphan_row = dict(gp_segment_ids=gp_segment_ids,
                                 toast_table_name=toast_table_name,
                                 expected_table_name=expected_table_name,
                                 dependent_table_name=dependent_table_name)
            if expected_table_name == "" and dependent_table_name == "":
                self.double_orphans.append(orphan_row)
            elif expected_table_name == "":
                self.reference_orphans.append(orphan_row)
            elif dependent_table_name == "":
                self.dependency_orphans.append(orphan_row)
            else:
                self.mismatch_orphans.append(orphan_row)

        return False

    def get_error_log_output(self):
        log_output = ""
        if len(self.reference_orphans) > 0:
            # output goes here
        if len(self.dependency_orphans) > 0:
            # output goes here
        if len(self.mismatch_orphans) > 0:
            # output goes here
        if len(self.double_orphans) > 0:
            # output goes here
        return log_output

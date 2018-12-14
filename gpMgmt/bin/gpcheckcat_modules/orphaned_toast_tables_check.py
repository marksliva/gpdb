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
        # TODO: We're grabbing names for everything in case we need to log things;
        #       remove them if we don't end up using them
        self.orphaned_toast_tables_query = """
SELECT
    array_agg(gp_segment_id),
    toast_table_oid,
    expected_table_oid,
    dependent_table_oid
FROM (
    SELECT
        tst.gp_segment_id,
        -- tst.relname AS toast_table_name,
        tst.oid AS toast_table_oid,
        -- tbl.relname AS expected_table_name,
        tbl.oid AS expected_table_oid,
        -- dep.refobjid::regclass::text AS dependent_table_name,
        dep.refobjid AS dependent_table_oid
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
        -- tst.relname AS toast_table_name,
        tst.oid AS toast_table_oid,
        -- tbl.relname AS expected_table_name,
        tbl.oid AS expected_table_oid,
        -- dep.refobjid::regclass::text AS dependent_table_name,
        dep.refobjid AS dependent_table_oid
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
    ORDER BY toast_table_oid, expected_table_oid, dependent_table_oid, gp_segment_id
) AS subquery
GROUP BY toast_table_oid, expected_table_oid, dependent_table_oid;
"""

    def runCheck(self, db_connection):
        orphaned_toast_tables = db_connection.query(self.orphaned_toast_tables_query).getresult()
        if len(orphaned_toast_tables) == 0:
            return True

        self.reference_orphans = [] # orphaned by missing reltoastrelid value
        self.dependency_orphans = [] # orphaned by missing pg_depend entry
        self.mismatch_orphans = [] # orphaned by incorrect reltoastrelid value
        self.double_orphans = [] # orphaned by both missing/incorrect reltoastrelid value and missing pg_depend entry

        for (gp_segment_ids, toast_table_oid, expected_table_oid, dependent_table_oid) in orphaned_toast_tables:
            orphan_row = dict(gp_segment_ids=gp_segment_ids,
                                 toast_table_oid=toast_table_oid,
                                 expected_table_oid=expected_table_oid,
                                 dependent_table_oid=dependent_table_oid)
            if expected_table_oid is None and dependent_table_oid is None:
                self.double_orphans.append(orphan_row)
            elif expected_table_oid is None:
                self.reference_orphans.append(orphan_row)
            elif dependent_table_oid is None:
                self.dependency_orphans.append(orphan_row)
            else:
                # Doesn't work with two tables, can probably remove this
                pass
                #self.mismatch_orphans.append(orphan_row)

        return False

    def get_repair_statements(self):
        repair_statements = []
        if len(self.reference_orphans) > 0:
            # Update reltoastrelid using dependent_table_oid, since we don't have expected_table_oid
            for orphan in self.reference_orphans:
                repair_statements.append("UPDATE pg_class SET reltoastrelid = %d WHERE oid = %s;" %
                                          (orphan["toast_table_oid"], orphan["dependent_table_oid"]))
        if len(self.dependency_orphans) > 0:
            # Insert a pg_depend entry using using expected_table_oid, since we don't have dependent_table_oid
            # 1259 is the reserved oid for pg_class and 'i' means internal dependency; these are safe to hard-code
            for orphan in self.dependency_orphans:
                repair_statements.append("INSERT INTO pg_depend VALUES (1259, %d, 0, 1259, %d, 0, 'i');" %
                                          (orphan["toast_table_oid"], orphan["expected_table_oid"]))
        if len(self.mismatch_orphans) > 0:
            # Update the pg_depend entry pointing to dependent_table_oid to point to expected_table_oid again
            for orphan in self.mismatch_orphans:
                repair_statements.append("UPDATE pg_depend SET refobjid = %d WHERE objid = %d AND refobjid = %d;" %
                                          (orphan["expected_table_oid"], orphan["toast_table_oid"], orphan["dependent_table_oid"]))
        if len(self.double_orphans) > 0:
            # First, attempt to determine the original table's oid from the name of the TOAST table.
            # If it's a valid oid and that table exists, update its pg_class entry and add a pg_depend entry.
            # If it's invalid, the TOAST table has been renamed and there's nothing we can do.
            # If the table doesn't exist, we can safely delete the TOAST table.
            plpgsql_func = """DO $$
DECLARE
  parent_table_oid oid := 0;
  check_oid oid := 0;
  toast_table_name text := '';
BEGIN
  BEGIN
    SELECT oid FROM pg_class WHERE oid = {0} INTO parent_table_oid;
  EXCEPTION WHEN OTHERS THEN
    -- Invalid oid; maybe the TOAST table was renamed.  Do nothing.
    RETURN;
  END;

  SELECT count(oid) FROM pg_class WHERE oid = parent_table_oid INTO check_oid;
  SELECT {1}::regclass::text INTO toast_table_name;
  IF check_oid = 0 THEN
    -- Parent table doesn't exist.  Drop TOAST table.
    DROP TABLE toast_table_name;
    RETURN;
  END IF;

  -- Parent table exists and is valid; go ahead with UPDATE and INSERT
  UPDATE pg_class SET reltoastrelid = {1} WHERE oid = parent_table_oid;
  INSERT INTO pg_depend VALUES (1259, {1}, 0, 1259, parent_table_oid, 0, 'i');
END
$$;"""
            for orphan in self.double_orphans:
                # Given a TOAST table oid, get its name, extract the original table's oid from the name, and cast to oid
                extract_oid_expr =  "trim('pg_toast.pg_toast_' from %d::regclass::text)::int::regclass::oid" % orphan["toast_table_oid"]
                repair_statements.append(plpgsql_func.format(extract_oid_expr, orphan["toast_table_oid"]))
        if len(repair_statements) > 0:
            repair_statements = ["SET allow_system_table_mods=true;"] + repair_statements
        return repair_statements

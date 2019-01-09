#!/usr/bin/env python

try:
    from gppylib.db import dbconn

except ImportError, e:
    sys.exit('Error: unable to import module: ' + str(e))

class OrphanedToastTablesCheck:


    def __init__(self):
        self.issues = []  # a flat list of all orphaned issues
        self.reference_orphans = []  # orphaned by missing reltoastrelid value
        self.dependency_orphans = []  # orphaned by missing pg_depend entry
        self.mismatch_orphans = []  # orphaned by incorrect reltoastrelid value
        self.double_orphans = []  # orphaned by both missing/incorrect reltoastrelid value and missing pg_depend entry
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
    gp_segment_id AS content_id,
    toast_table_oid,
    toast_table_name,
    expected_table_oid,
    expected_table_name,
    dependent_table_oid,
    dependent_table_name
FROM (
    SELECT
        tst.gp_segment_id,
        tst.oid AS toast_table_oid,
        tst.relname AS toast_table_name,
        tbl.oid AS expected_table_oid,
        tbl.relname AS expected_table_name,
        dep.refobjid AS dependent_table_oid,
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
        tst.oid AS toast_table_oid,
        tst.relname AS toast_table_name,
        tbl.oid AS expected_table_oid,
        tbl.relname AS expected_table_name,
        dep.refobjid AS dependent_table_oid,
        dep.refobjid::regclass::text AS dependent_table_name
    FROM gp_dist_random('pg_class') tst
        LEFT JOIN gp_dist_random('pg_depend') dep ON tst.oid = dep.objid AND tst.gp_segment_id = dep.gp_segment_id
        LEFT JOIN gp_dist_random('pg_class') tbl ON tst.oid = tbl.reltoastrelid AND tst.gp_segment_id = tbl.gp_segment_id
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
GROUP BY gp_segment_id, toast_table_oid, toast_table_name, expected_table_oid, expected_table_name, dependent_table_oid, dependent_table_name;
"""

    def runCheck(self, db_connection):
        orphaned_toast_tables = db_connection.query(self.orphaned_toast_tables_query).dictresult()
        if len(orphaned_toast_tables) == 0:
            return True

        for row in orphaned_toast_tables:
            if row['expected_table_oid'] is None and row['dependent_table_oid'] is None:
                self.double_orphans.append(row)
                self.issues.append(dict(
                    row=row,
                    catname=row['toast_table_name'],
                    oid=row['toast_table_oid'],
                    issue_type='double_orphans',
                    issue_description='Found orphaned TOAST table due to "double orphan" caused by missing reltoastrelid and pg_depend entry.',
                    issue_cause='is an orphan TOAST table.'))
            elif row['expected_table_oid'] is None:
                self.reference_orphans.append(row)
                self.issues.append(dict(
                    row=row,
                    catname=row['dependent_table_name'],
                    oid=row['dependent_table_oid'],
                    issue_type='reference_orphans',
                    issue_description='Found orphaned TOAST table due to "bad reference" caused by missing reltoastrelid.',
                    issue_cause='''has an orphaned TOAST table '%s' (oid: %s).''' % (row['toast_table_name'], row['toast_table_oid'])))
            elif row['dependent_table_oid'] is None:
                self.dependency_orphans.append(row)
                self.issues.append(dict(
                    row=row,
                    catname=row['expected_table_name'],
                    oid=row['expected_table_oid'],
                    issue_type='dependency_orphans',
                    issue_description='Found orphaned TOAST table due to "bad dependency" caused by missing pg_depend entry.',
                    issue_cause='''has an orphaned TOAST table '%s' (oid: %s).''' % (row['toast_table_name'], row['toast_table_oid'])))
            else:
                self.mismatch_orphans.append(row)
                self.issues.append(dict(
                    row=row,
                    catname=row['dependent_table_name'],
                    oid=row['dependent_table_oid'],
                    issue_type='mismatch_orphans',
                    issue_description='Found orphaned TOAST table due to "mismatch" caused by a reltoastrelid pointing to an incorrect TOAST table.',
                    issue_cause='''has an orphaned TOAST table '%s' (oid: %s). Expected dependent table to be '%s' (oid: %s).''' % (row['toast_table_name'], row['toast_table_oid'], row['expected_table_name'], row['expected_table_oid'])))

        return False

    def get_issues(self):
        return self.issues

    def get_fix_text(self):
        log_output = ['\nORPHAN TOAST TABLE FIXES:', '===================================================================']
        for issue_type in set(map(lambda issue: issue['issue_type'], self.issues)):
            if issue_type == 'double_orphans':
                log_output.append(filter(lambda issue: issue['issue_type'] == issue_type, self.get_issues_by_type())[0]['issue_header'])
                log_output.append('  To fix update the TOAST table pg_class entry reltoastrelid to be match the dependent table oid.\n')
            elif issue_type == 'reference_orphans':
                log_output.append(filter(lambda issue: issue['issue_type'] == issue_type, self.get_issues_by_type())[0]['issue_header'])
                log_output.append('  To fix update the TOAST table pg_class entry reltoastrelid to be match the dependent table oid.\n')
            elif issue_type == 'dependency_orphans':
                log_output.append(filter(lambda issue: issue['issue_type'] == issue_type, self.get_issues_by_type())[0]['issue_header'])
                log_output.append('  To fix update the TOAST table pg_class entry reltoastrelid to be match the dependent table oid.\n')
            elif issue_type == 'mismatch_orphans':
                log_output.append(filter(lambda issue: issue['issue_type'] == issue_type, self.get_issues_by_type())[0]['issue_header'])
                log_output.append('  To fix update the TOAST table pg_class entry reltoastrelid to be match the dependent table oid.\n')

        return '\n'.join(log_output)

    def get_issues_by_type(self):
        issues_by_type = []

        if self.double_orphans:
            issues_by_type.append({
                'issue_type': 'double_orphans',
                'issue_header': 'Double Orphan: orphaned TOAST table due to missing reltoastrelid and pg_depend entry.',
                'rows': self.double_orphans
            })

        if self.reference_orphans:
            issues_by_type.append({
                'issue_type': 'reference_orphans',
                'issue_header': 'Bad Reference: orphaned TOAST tables due to missing reltoastrelid',
                'rows': self.reference_orphans
            })

        if self.dependency_orphans:
            issues_by_type.append({
                'issue_type': 'dependency_orphans',
                'issue_header': 'Bad Dependency: orphaned TOAST tables due to missing pg_depend entry',
                'rows': self.dependency_orphans
            })

        if self.mismatch_orphans:
            issues_by_type.append({
                'issue_type': 'mismatch_orphans',
                'issue_header': 'Mismatch: orphaned TOAST tables due to reltoastrelid pointing to an incorrect TOAST table',
                'rows': self.mismatch_orphans
            })

        return issues_by_type

    def get_repair_statements(self, segments):
        content_id_to_segment_map = self.__get_content_id_to_segment_map(segments)

        for row in self.reference_orphans:
            repair_statement = "UPDATE \"pg_class\" SET reltoastrelid = %d WHERE oid = %s;" % (row["toast_table_oid"], row["dependent_table_oid"])
            content_id_to_segment_map[row['content_id']]['repair_statements'].append(repair_statement)

        for row in self.dependency_orphans:
            # 1259 is the reserved oid for pg_class and 'i' means internal dependency; these are safe to hard-code
            repair_statement = "INSERT INTO pg_depend VALUES (1259, %d, 0, 1259, %d, 0, 'i');" % (row["toast_table_oid"], row["expected_table_oid"])
            content_id_to_segment_map[row['content_id']]['repair_statements'].append(repair_statement)

        # for row in self.mismatch_orphans:  # The following repair does not work with two or more tables, so let the user repair manually for safety.
        #     repair_statement = "UPDATE pg_depend SET refobjid = %d WHERE objid = %d AND refobjid = %d;" % (row["expected_table_oid"], row["toast_table_oid"], row["dependent_table_oid"])
        #     content_id_to_segment_map[row['content_id']]['repair_statements'].append(repair_statement)

        for row in self.double_orphans:
            # Given a TOAST table oid, get its name, extract the original table's oid from the name, and cast to oid
            extract_oid_expr = "trim('pg_toast.pg_toast_' from %d::regclass::text)::int::regclass::oid" % row["toast_table_oid"]
            repair_statement = self.__get_double_orphan_repair_statement(extract_oid_expr, row["toast_table_oid"])
            content_id_to_segment_map[row['content_id']]['repair_statements'].append(repair_statement)

        segments_with_repair_statements = filter(lambda segment: len(segment['repair_statements']) > 0, content_id_to_segment_map.values())
        for segment in segments_with_repair_statements:
            segment['repair_statements'] = ["SET allow_system_table_mods=true;"] + segment['repair_statements']

        return segments_with_repair_statements

    def __get_content_id_to_segment_map(self, segments):
        content_id_to_segment = {}
        for segment in segments.values():
            segment['repair_statements'] = []
            content_id_to_segment[segment['content']] = segment

        return content_id_to_segment

    def __get_double_orphan_repair_statement(self, extract_oid_expr, toast_table_oid):
        # First, attempt to determine the original table's oid from the name of the TOAST table.
        # If it's a valid oid and that table exists, update its pg_class entry and add a pg_depend entry.
        # If it's invalid, the TOAST table has been renamed and there's nothing we can do.
        # If the table doesn't exist, we can safely delete the TOAST table.
        return """DO $$
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
$$;""".format(extract_oid_expr, toast_table_oid)

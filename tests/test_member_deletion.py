"""Regression tests for member foreign-key cleanup."""

import unittest
from unittest.mock import AsyncMock, Mock

from openvort.web.routers.members import _cleanup_member_references, _quote_pg_identifier


class MemberReferenceCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_uses_database_foreign_keys(self):
        session = Mock()
        session.execute = AsyncMock()

        catalog_result = Mock()
        catalog_result.mappings.return_value.all.return_value = [
            {
                "schema_name": "public",
                "table_name": "flow_projects",
                "column_name": "owner_id",
                "is_nullable": True,
                "delete_action": "a",
            },
            {
                "schema_name": "public",
                "table_name": "flow_project_stars",
                "column_name": "member_id",
                "is_nullable": False,
                "delete_action": "a",
            },
            {
                "schema_name": "public",
                "table_name": "member_roles",
                "column_name": "member_id",
                "is_nullable": False,
                "delete_action": "c",
            },
        ]
        session.execute.side_effect = [Mock(), Mock(), catalog_result, Mock(), Mock()]

        await _cleanup_member_references(session, ["member-1"])

        self.assertEqual(session.execute.await_count, 5)
        statements = [str(call.args[0]) for call in session.execute.await_args_list]
        self.assertIn(
            'UPDATE "public"."flow_projects" SET "owner_id" = NULL WHERE "owner_id" = ANY(:ids)',
            statements[3],
        )
        self.assertIn(
            'DELETE FROM "public"."flow_project_stars" WHERE "member_id" = ANY(:ids)',
            statements[4],
        )
        self.assertFalse(any('DELETE FROM "public"."member_roles"' in statement for statement in statements))
        self.assertFalse(any("designer_id" in statement or "reviewer_id" in statement for statement in statements))
        for index, call in enumerate(session.execute.await_args_list):
            if index == 2:  # PostgreSQL catalog query has no bound parameters.
                continue
            self.assertEqual(call.args[1], {"ids": ["member-1"]})

    async def test_cleanup_with_no_member_ids_does_not_query_database(self):
        session = Mock()
        session.execute = AsyncMock()

        await _cleanup_member_references(session, [])

        session.execute.assert_not_awaited()

    def test_quote_pg_identifier_escapes_double_quotes(self):
        self.assertEqual(_quote_pg_identifier('odd"name'), '"odd""name"')


if __name__ == "__main__":
    unittest.main()

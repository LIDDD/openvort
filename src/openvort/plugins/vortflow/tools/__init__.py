"""VortFlow AI Tools

工具索引（在 plugin.py 的 get_tools() 中注册）：

- project.CreateProjectTool         vortflow_create_project
- manage_project.ManageProjectTool  vortflow_manage_project
- intake.IntakeStoryTool            vortflow_intake_story
- create_task.CreateTaskTool        vortflow_create_task
- create_bug.CreateBugTool          vortflow_create_bug
- assign.AssignTool                 vortflow_assign
- progress.UpdateProgressTool       vortflow_update_progress
- update_work_item.UpdateWorkItemTool vortflow_update_work_item
- delete_work_item.DeleteWorkItemTool vortflow_delete_work_item
- comment.CommentTool               vortflow_comment
- link_work_items.LinkWorkItemsTool vortflow_link_work_items
- manage_iteration.ManageIterationTool vortflow_manage_iteration
- manage_version.ManageVersionTool  vortflow_manage_version
- manage_test_case.ManageTestCaseTool vortflow_manage_test_case
- manage_test_plan.ManageTestPlanTool vortflow_manage_test_plan
- manage_test_report.ManageTestReportTool vortflow_manage_test_report
- query.QueryTool                   vortflow_query
- group_bind.GroupBindTool          vortflow_group_bind

约定：所有工具使用相同的 entity_type 枚举（story/task/bug），
状态值与 engine.py 的 StoryState/TaskState/BugState 保持一致。
"""

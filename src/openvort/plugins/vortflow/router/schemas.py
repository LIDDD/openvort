from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    code: str = ""
    color: str = "#3b82f6"
    description: str = ""
    start_date: str | None = None
    end_date: str | None = None
    owner_id: str | None = None
    member_ids: list[str] = []
    repo_ids: list[str] = []

class ProjectUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    color: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    owner_id: str | None = None

class StoryCreate(BaseModel):
    project_id: str
    title: str
    description: str = ""
    priority: int = 3
    # 0-100 精排分数；不传则根据 priority 派生段起始值（1→80、2→60、3→40、4→20）
    priority_score: int | None = None
    parent_id: str | None = None
    assignee_id: str | None = None
    tags: list[str] = []
    collaborators: list[str] = []
    attachments: list[dict] = []
    plan_start: str | None = None
    deadline: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    test_time: str | None = None
    draft_time: str | None = None
    release_time: str | None = None
    repo_id: str | None = None
    branch: str | None = None

class StoryUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    state: str | None = None
    priority: int | None = None
    # 0-100 精排分数；同时传 priority 与 priority_score 时以 priority_score 为准
    priority_score: int | None = None
    parent_id: str | None = None
    assignee_id: str | None = None
    tags: list[str] | None = None
    collaborators: list[str] | None = None
    attachments: list[dict] | None = None
    plan_start: str | None = None
    deadline: str | None = None
    test_time: str | None = None
    draft_time: str | None = None
    release_time: str | None = None
    pm_id: str | None = None
    project_id: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    repo_id: str | None = None
    branch: str | None = None
    progress: int | None = None

class StoryReorder(BaseModel):
    """需求拖拽排序请求体。

    语义（互斥模式之一）：
    - 指定 before_id 或 after_id：插入到该锚点附近（同 parent，sort_order 取相邻区间中点）
    - 指定 parent_id（且不传 before_id/after_id）：变更父需求，sort_order 取该 parent 下末尾 +1024
    - 同时传 parent_id 与 before_id/after_id：先确认目标 parent，再按相邻锚点定位
    """
    parent_id: str | None = None  # null 表示挪到顶层；不传则保持原 parent
    before_id: str | None = None  # 插到该需求之前
    after_id: str | None = None  # 插到该需求之后


class TaskReorder(BaseModel):
    """任务拖拽排序请求体。

    支持改变 story_id（嵌入到需求下）和 parent_id（成为另一任务的子任务），
    以及在锚点附近插入。锚点优先级：anchor.story_id + anchor.parent_id > body 显式指定。
    """
    story_id: str | None = None  # 显式指定所属需求；为空字符串/None 由后端判断（保留原值或锚点决定）
    parent_id: str | None = None  # 显式指定父任务；null 表示顶层任务
    before_id: str | None = None
    after_id: str | None = None


class BugReorder(BaseModel):
    """缺陷拖拽排序请求体。

    支持改变 story_id（嵌入到需求下）和 task_id（嵌入到任务下），以及锚点附近插入。
    缺陷之间没有父子关系，inside 模式只允许目标为需求或任务。
    """
    story_id: str | None = None
    task_id: str | None = None
    before_id: str | None = None
    after_id: str | None = None


class TaskCreate(BaseModel):
    project_id: str | None = None
    story_id: str | None = None
    parent_id: str | None = None
    title: str
    description: str = ""
    task_type: str = "fullstack"
    assignee_id: str | None = None
    creator_id: str | None = None
    tags: list[str] = []
    collaborators: list[str] = []
    attachments: list[dict] = []
    estimate_hours: float | None = None
    priority_score: int | None = None
    plan_start: str | None = None
    deadline: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    repo_id: str | None = None
    branch: str | None = None

class TaskUpdate(BaseModel):
    project_id: str | None = None
    title: str | None = None
    description: str | None = None
    task_type: str | None = None
    state: str | None = None
    assignee_id: str | None = None
    tags: list[str] | None = None
    collaborators: list[str] | None = None
    attachments: list[dict] | None = None
    estimate_hours: float | None = None
    actual_hours: float | None = None
    priority_score: int | None = None
    plan_start: str | None = None
    deadline: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    repo_id: str | None = None
    branch: str | None = None
    progress: int | None = None

class BugCreate(BaseModel):
    project_id: str | None = None
    story_id: str | None = None
    task_id: str | None = None
    title: str
    description: str = ""
    severity: int = 3
    priority_score: int | None = None
    tags: list[str] = []
    collaborators: list[str] = []
    attachments: list[dict] = []
    assignee_id: str | None = None
    # 历史保留字段：与 assignee_id 共同表示「负责人」，前端展示口径为 assignee_id || developer_id。
    # 自 2026-05-06 起前端写入时双写以保持一致；新接入方建议只填 assignee_id，由调用层同步。
    developer_id: str | None = None
    plan_start: str | None = None
    deadline: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    repo_id: str | None = None
    branch: str | None = None

class BugUpdate(BaseModel):
    project_id: str | None = None
    title: str | None = None
    description: str | None = None
    severity: int | None = None
    priority_score: int | None = None
    state: str | None = None
    assignee_id: str | None = None
    developer_id: str | None = None
    tags: list[str] | None = None
    collaborators: list[str] | None = None
    attachments: list[dict] | None = None
    estimate_hours: float | None = None
    actual_hours: float | None = None
    plan_start: str | None = None
    deadline: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    repo_id: str | None = None
    branch: str | None = None

class TransitionBody(BaseModel):
    target_state: str

class ProjectMemberBody(BaseModel):
    member_id: str
    role: str = "member"


class IterationCreate(BaseModel):
    project_id: str
    name: str
    goal: str = ""
    owner_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str = "planning"
    estimate_hours: float | None = None


class IterationUpdate(BaseModel):
    name: str | None = None
    goal: str | None = None
    owner_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    estimate_hours: float | None = None


class VersionCreate(BaseModel):
    project_id: str
    name: str
    description: str = ""
    owner_id: str | None = None
    planned_release_at: str | None = None
    actual_release_at: str | None = None
    progress: int = 0
    release_date: str | None = None  # backward compatibility
    status: str = "planning"


class VersionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    owner_id: str | None = None
    planned_release_at: str | None = None
    actual_release_at: str | None = None
    progress: int | None = None
    release_date: str | None = None  # backward compatibility
    status: str | None = None


class IterationStoryBody(BaseModel):
    story_id: str
    story_order: int = 0


class IterationTaskBody(BaseModel):
    task_id: str
    task_order: int = 0


class IterationBugBody(BaseModel):
    bug_id: str
    bug_order: int = 0

class VersionStoryBody(BaseModel):
    story_id: str
    added_reason: str = ""
    story_order: int = 0

class VersionBugBody(BaseModel):
    bug_id: str
    bug_order: int = 0


class ViewCreate(BaseModel):
    name: str
    work_item_type: str  # 需求/任务/缺陷
    scope: str = "personal"  # personal/shared
    filters: dict = {}
    columns: list = []

class ViewUpdate(BaseModel):
    name: str | None = None
    filters: dict | None = None
    columns: list | None = None
    view_order: int | None = None


class ColumnSettingBody(BaseModel):
    work_item_type: str  # 需求/任务/缺陷
    columns: list  # [{"key":"workNo","visible":true}, ...]


class CommentCreate(BaseModel):
    content: str
    mentions: list[str] = []


class WorkItemLinkCreate(BaseModel):
    source_type: str  # story/task/bug
    source_id: str
    target_type: str  # story/task/bug
    target_id: str


class TagCreate(BaseModel):
    name: str
    color: str = "#3b82f6"

class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None

class TagReorder(BaseModel):
    ids: list[str]

class TagMigrate(BaseModel):
    target_tag_id: str | None = None


class StatusCreate(BaseModel):
    name: str
    icon: str = "○"
    icon_color: str = "#3b82f6"
    command: str = ""
    work_item_types: list[str] = []

class StatusUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    icon_color: str | None = None
    command: str | None = None
    work_item_types: list[str] | None = None


class TestModuleCreate(BaseModel):
    project_id: str
    parent_id: str | None = None
    name: str

class TestModuleUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    sort_order: int | None = None

class TestCaseCreate(BaseModel):
    project_id: str
    module_id: str | None = None
    title: str
    precondition: str = ""
    notes: str = ""
    case_type: str = "functional"
    priority: int = 2
    maintainer_id: str | None = None
    steps: list[dict] = []

class TestCaseUpdate(BaseModel):
    module_id: str | None = None
    title: str | None = None
    precondition: str | None = None
    notes: str | None = None
    case_type: str | None = None
    priority: int | None = None
    maintainer_id: str | None = None
    review_result: str | None = None
    steps: list[dict] | None = None

class TestCaseWorkItemBody(BaseModel):
    test_case_id: str
    entity_type: str  # story/task/bug
    entity_id: str


class DescriptionTemplateUpdate(BaseModel):
    content: str = ""


class BatchArchiveBody(BaseModel):
    ids: list[str]
    type: str  # story/task/bug
    archived: bool

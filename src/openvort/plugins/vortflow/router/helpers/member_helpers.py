"""成员显示名解析。"""


async def _resolve_member_name(session, member_id: str | None) -> str:
    if not member_id:
        return ""
    from openvort.contacts.models import Member
    member = await session.get(Member, member_id)
    return member.name if member else ""

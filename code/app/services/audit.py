"""BL-17 minimal append-only audit trail."""

import json

from .. import db


def log(connection, actor: str, action: str, object_type: str,
        object_id: str | int | None = None, session_id: int | None = None,
        before=None, after=None) -> None:
    connection.execute(
        "INSERT INTO nhat_ky_kiem_toan"
        " (ca_thi,chu_the,hanh_dong,loai_doi_tuong,ma_doi_tuong,du_lieu_truoc,"
        " du_lieu_sau,tao_luc) VALUES (?,?,?,?,?,?,?,?)",
        (session_id, actor, action, object_type,
         None if object_id is None else str(object_id),
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         db.bay_gio()),
    )

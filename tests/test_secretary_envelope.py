from __future__ import annotations

from duedatehq.core.secretary_envelope import envelope_from_response


def test_guidance_response_stays_chat_only():
    envelope = envelope_from_response(
        {
            "message": "你好！有什么需要我处理的？",
            "view": {"type": "GuidanceCard", "data": {"message": "你好"}},
        }
    )

    assert envelope["reply"] == "你好！有什么需要我处理的？"
    assert envelope["action"]["type"] == "none"


def test_material_response_uses_render_gesture():
    envelope = envelope_from_response(
        {
            "message": "好的，我把客户清单拿出来给你看。",
            "view": {"type": "ClientListCard", "data": {"total": 12}},
        }
    )

    assert envelope["reply"] == "好的，我把客户清单拿出来给你看。"
    assert envelope["action"]["type"] == "render"
    assert envelope["action"]["announce"] == "拿出材料"
    assert envelope["action"]["template"] == "ClientListCard"

import test from "node:test";
import assert from "node:assert/strict";
import { feishuDetails, shouldHandleMessage } from "../src/feishu.js";

test("only a direct bot mention or a severe task issue is handled", () => {
  const ordinary = { event: { message: { content: JSON.stringify({ text: "今天辛苦了" }), mentions: [] } } };
  const mention = { event: { message: { content: JSON.stringify({ text: "@牛顿 看一下 PR #12" }), mentions: [{ id: "ou_bot" }] } } };
  const severe = { event: { message: { content: JSON.stringify({ text: "PR 冲突，合并失败，一直不通过" }), mentions: [] } } };
  assert.equal(shouldHandleMessage(ordinary, "ou_bot"), false);
  assert.equal(shouldHandleMessage(mention, "ou_bot"), true);
  assert.equal(shouldHandleMessage(severe, "ou_bot"), true);
});

test("Feishu event details preserve message and sender identifiers", () => {
  const payload = {
    header: { event_type: "im.message.receive_v1" },
    event: {
      sender: { sender_id: { open_id: "ou_sender" } },
      message: { message_id: "om_1", chat_id: "oc_1", content: JSON.stringify({ text: "@牛顿 查 PR" }), mentions: [] },
    },
  };
  assert.deepEqual(feishuDetails(payload), {
    eventType: "im.message.receive_v1",
    messageId: "om_1",
    chatId: "oc_1",
    senderOpenId: "ou_sender",
    text: "@牛顿 查 PR",
    mentions: [],
    memberOpenId: null,
    memberName: "新成员",
  });
});

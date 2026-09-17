import test from "node:test";
import assert from "node:assert/strict";
import { parseStageNumber, projectForChat, projectForRepository } from "../src/task-board.js";

test("stage parsing supports Arabic and Chinese stage names", () => {
  assert.equal(parseStageNumber("阶段 8：真实问题"), 8);
  assert.equal(parseStageNumber("阶段八：真实问题"), 8);
  assert.equal(parseStageNumber("阶段十一：真实问题"), 11);
});

test("repository and chat routing remain project-specific", () => {
  const env = {
    FEISHU_CODESENSE_CHAT_IDS: "oc_codesense, oc_total",
    FEISHU_CAIFUSI_CHAT_IDS: "oc_caifusi",
  };
  assert.equal(projectForRepository(env, "XiaoCow666/CodeSense").key, "codesense");
  assert.equal(projectForRepository(env, "XiaoCow666/Caifusi").key, "caifusi");
  assert.equal(projectForChat(env, "oc_codesense").key, "codesense");
  assert.equal(projectForChat(env, "oc_caifusi").key, "caifusi");
  assert.equal(projectForChat(env, "oc_unknown"), null);
});

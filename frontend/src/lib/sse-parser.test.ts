import { expect, test } from "vitest";
import { SSEParser } from "./sse-parser";
import { setApiBaseUrl, resetApiBaseUrl } from "./api";
import { getAuthToken, setAuthToken } from "./auth";
import { dateText } from "./query";
test.each(["\n", "\r\n"])(
  "SSE framing and arbitrary chunk boundaries: %j",
  (newline) => {
    const parser = new SSEParser();
    const frame =
      "event: gallery_status" + newline + 'data: {"gid":1}' + newline + newline;
    const events = [...frame].flatMap((character) => parser.feed(character));
    expect(events).toEqual([{ event: "gallery_status", data: '{"gid":1}' }]);
  },
);
test("multiple events and multiline data", () => {
  expect(
    new SSEParser().feed(
      ": comment\nevent: snapshot\ndata: one\ndata: two\n\nevent: heartbeat\ndata: {}\n\n",
    ),
  ).toEqual([
    { event: "snapshot", data: "one\ntwo" },
    { event: "heartbeat", data: "{}" },
  ]);
});
test("changing backend clears the previous backend token", () => {
  setAuthToken("old-token");
  setApiBaseUrl("https://example.test/api/v1");
  expect(getAuthToken()).toBeNull();
  resetApiBaseUrl();
});
test("timestamps already carrying a timezone are preserved", () => {
  expect(dateText("2026-01-01T00:00:00Z")).not.toContain("Invalid");
  expect(dateText("2026-01-01T00:00:00+08:00")).not.toContain("Invalid");
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import Login from "./Login";
import api from "@/lib/api";
import { getAuthToken } from "@/lib/auth";
test("login stores the token and opens the workspace", async () => {
  vi.spyOn(api, "post").mockResolvedValue({
    data: { access_token: "test-token" },
  });
  const success = vi.fn();
  const user = userEvent.setup();
  render(<Login onLoginSuccess={success} />);
  await user.type(screen.getByLabelText("用户名"), "admin");
  await user.type(screen.getByLabelText("密码"), "example");
  await user.click(screen.getByRole("button", { name: "登录" }));
  expect(success).toHaveBeenCalledOnce();
  expect(getAuthToken()).toBe("test-token");
});
test("failed login remains on the form", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new Error("登录失败"));
  const success = vi.fn();
  const user = userEvent.setup();
  render(<Login onLoginSuccess={success} />);
  await user.type(screen.getByLabelText("用户名"), "admin");
  await user.type(screen.getByLabelText("密码"), "wrong");
  await user.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("登录失败");
  expect(success).not.toHaveBeenCalled();
});

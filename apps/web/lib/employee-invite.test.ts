import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the data layer so we test the invite ORCHESTRATION (validation order,
// existing-user lookup, push best-effort) without touching Firestore. The
// generics give `.mock.calls[0][0]` a typed shape so tsc can index it.
const requestsMock = {
  createScheduleRequest: vi.fn<(input: Record<string, unknown>) => Promise<string>>(
    async () => "new-req-id"
  ),
  getUserByEmail: vi.fn<(email: string) => Promise<null | { uid: string }>>(
    async () => null
  ),
  triggerPushNotification: vi.fn<
    (input: { toUserUids: string[]; notificationTitle: string }) => Promise<void>
  >(async () => {}),
};

vi.mock("./requests", () => requestsMock);

const { sendEmployeeInvite, InviteError, isEmailValid } = await import(
  "./employee-invite"
);

import type { EmployeeDetails } from "./types";
import type { ScheduleRequest } from "./requests-types";

function emp(email: string): EmployeeDetails {
  return {
    employee_name: email.split("@")[0],
    employee_email: email,
    // minimal role — not asserted here
    role: { is_creator: false, is_admin: false } as EmployeeDetails["role"],
  } as EmployeeDetails;
}

const BASE = {
  scheduleId: "sid1",
  scheduleName: "Team A",
  fromUserUid: "mgr-uid",
  fromUserEmail: "manager@x.com",
  employees: [] as EmployeeDetails[],
  pendingRequests: [] as ScheduleRequest[],
};

beforeEach(() => {
  requestsMock.createScheduleRequest.mockClear();
  requestsMock.getUserByEmail.mockClear();
  requestsMock.triggerPushNotification.mockClear();
  requestsMock.getUserByEmail.mockResolvedValue(null);
});

describe("isEmailValid", () => {
  it("accepts well-formed addresses and rejects malformed", () => {
    expect(isEmailValid("a@b.com")).toBe(true);
    expect(isEmailValid("  spaced@b.co  ")).toBe(true); // trims
    expect(isEmailValid("nope")).toBe(false);
    expect(isEmailValid("a@")).toBe(false);
  });
});

describe("sendEmployeeInvite — validations (Flutter add_employee_widget.dart)", () => {
  it("rejects self-addition", async () => {
    await expect(
      sendEmployeeInvite({ ...BASE, email: "manager@x.com" })
    ).rejects.toMatchObject({ code: "self" });
    expect(requestsMock.createScheduleRequest).not.toHaveBeenCalled();
  });

  it("rejects a duplicate existing employee", async () => {
    await expect(
      sendEmployeeInvite({
        ...BASE,
        email: "dup@x.com",
        employees: [emp("dup@x.com")],
      })
    ).rejects.toMatchObject({ code: "duplicate_employee" });
    expect(requestsMock.createScheduleRequest).not.toHaveBeenCalled();
  });

  it("rejects an invalid email", async () => {
    await expect(
      sendEmployeeInvite({ ...BASE, email: "not-an-email" })
    ).rejects.toMatchObject({ code: "invalid_email" });
  });

  it("rejects a duplicate pending invitation", async () => {
    const pending = [
      { to_user_identification: "again@x.com" } as ScheduleRequest,
    ];
    await expect(
      sendEmployeeInvite({
        ...BASE,
        email: "again@x.com",
        pendingRequests: pending,
      })
    ).rejects.toMatchObject({ code: "duplicate_request" });
    expect(requestsMock.createScheduleRequest).not.toHaveBeenCalled();
  });
});

describe("sendEmployeeInvite — success paths", () => {
  it("email-only invite (no account): writes request, NO push", async () => {
    requestsMock.getUserByEmail.mockResolvedValue(null);
    const res = await sendEmployeeInvite({ ...BASE, email: "new@x.com" }, "en");
    expect(res.requestId).toBe("new-req-id");
    expect(res.invitedExistingUser).toBe(false);
    expect(requestsMock.createScheduleRequest).toHaveBeenCalledTimes(1);
    const arg = requestsMock.createScheduleRequest.mock.calls[0][0];
    expect(arg).toMatchObject({
      isAddRequest: true,
      isJoinRequest: false,
      requestStatus: "ADD_RQUEST_PENDING",
      toUserUid: null,
      toUserIdentification: "new@x.com",
    });
    expect(requestsMock.triggerPushNotification).not.toHaveBeenCalled();
  });

  it("existing-account invite: writes request AND fires a push", async () => {
    requestsMock.getUserByEmail.mockResolvedValue({ uid: "invitee-uid" });
    const res = await sendEmployeeInvite(
      { ...BASE, email: "exists@x.com" },
      "he"
    );
    expect(res.invitedExistingUser).toBe(true);
    expect(requestsMock.createScheduleRequest).toHaveBeenCalledTimes(1);
    expect(
      requestsMock.createScheduleRequest.mock.calls[0][0]
    ).toMatchObject({ toUserUid: "invitee-uid" });
    expect(requestsMock.triggerPushNotification).toHaveBeenCalledTimes(1);
    // Push goes to the invitee; locale picks the Hebrew copy.
    const push = requestsMock.triggerPushNotification.mock.calls[0][0];
    expect(push.toUserUids).toEqual(["invitee-uid"]);
    expect(push.notificationTitle).toContain("עדכון");
  });

  it("a push failure does NOT roll back the invite (best-effort)", async () => {
    requestsMock.getUserByEmail.mockResolvedValue({ uid: "invitee-uid" });
    requestsMock.triggerPushNotification.mockRejectedValueOnce(
      new Error("fcm down")
    );
    const res = await sendEmployeeInvite({ ...BASE, email: "exists@x.com" });
    expect(res.requestId).toBe("new-req-id");
    expect(res.invitedExistingUser).toBe(true);
  });

  it("a user-lookup failure falls back to an email-only invite", async () => {
    requestsMock.getUserByEmail.mockRejectedValueOnce(new Error("offline"));
    const res = await sendEmployeeInvite({ ...BASE, email: "x@x.com" });
    expect(res.invitedExistingUser).toBe(false);
    expect(requestsMock.triggerPushNotification).not.toHaveBeenCalled();
  });
});

// Sanity: InviteError carries its code.
describe("InviteError", () => {
  it("exposes the machine-readable code", () => {
    const e = new InviteError("self");
    expect(e.code).toBe("self");
    expect(e.name).toBe("InviteError");
  });
});

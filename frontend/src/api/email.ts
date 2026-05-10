import client from "./client";

export interface EmailSendRequest {
  market?: string;
}

export const sendEmail = (data?: EmailSendRequest) => client.post("/email/send", data || {});

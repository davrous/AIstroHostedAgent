import { createHash, randomBytes } from "node:crypto";
import type { Request, Response } from "express";
import { z } from "zod";

export const conversationId = z.string().uuid();
export const renderId = z.string().regex(/^[a-f0-9]{32}$/);

export function conversationScope(browserKey: string, conversation: string): string {
  if (!/^[a-f0-9]{64}$/.test(browserKey)) throw new Error("Invalid browser session.");
  return createHash("sha256").update(`${browserKey}:${conversationId.parse(conversation)}`).digest("hex");
}

export function browserKey(req: Request, res: Response): string {
  const value = req.headers.cookie?.split(";").map(item => item.trim())
    .find(item => item.startsWith("aistro_browser="))?.slice("aistro_browser=".length);
  if (value && /^[a-f0-9]{64}$/.test(value)) return value;
  const key = randomBytes(32).toString("hex");
  res.cookie("aistro_browser", key, {
    httpOnly: true, sameSite: "strict", secure: req.secure,
    maxAge: 365 * 24 * 60 * 60 * 1000, path: "/",
  });
  return key;
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

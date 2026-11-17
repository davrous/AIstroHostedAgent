import { z } from "zod";

const longitude = z.number().finite().min(0).lt(360);
const latitude = z.number().finite().min(-90).max(90);
const point = z.tuple([longitude, latitude]);
const star = z.object({
  hip: z.number().int().positive(), magnitude: z.number().finite(), longitude, latitude,
});
const constellation = z.object({
  id: z.string(), name: z.string(), stars: z.array(star),
  paths: z.array(z.array(z.number().int())),
  boundaries: z.array(z.array(point)), longitude, latitude,
});
export const sceneSchema = z.object({
  instant: z.string().datetime({ offset: true }), longitude, latitude,
  signs: z.array(z.tuple([z.string(), z.string()])).length(12),
  colors: z.array(z.string().regex(/^#[a-fA-F0-9]{6}$/)).length(12),
  elevation: z.number().finite(), azimuth: z.number().finite(),
  constellations: z.array(constellation).length(13),
  solarConstellation: z.string(),
  requestUrl: z.string().url().refine(value =>
    new URL(value).origin === "https://ssd.jpl.nasa.gov"
    && new URL(value).pathname === "/api/horizons.api"),
  catalogueSource: z.string().url().refine(value =>
    new URL(value).origin === "https://github.com"),
  catalogueLicense: z.string(),
});
export const manifestSchema = z.object({
  version: z.literal(1), id: z.string().regex(/^[a-f0-9]{32}$/),
  instant: z.string().datetime({ offset: true }),
  createdAt: z.string().datetime({ offset: true }),
  sign: z.string(), degrees: z.number().min(0).lt(30),
  longitude, latitude, solarConstellation: z.string(),
  timeAssumption: z.string(), dataSize: z.number().int().positive(),
});
export type SceneData = z.infer<typeof sceneSchema>;
export type Manifest = z.infer<typeof manifestSchema>;

export function formatInstant(instant: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "long", timeStyle: "short", timeZone: "UTC",
  }).format(new Date(instant)) + " UTC";
}

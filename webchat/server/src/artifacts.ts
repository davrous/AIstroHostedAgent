import { DefaultAzureCredential } from "@azure/identity";
import { BlobServiceClient } from "@azure/storage-blob";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { config } from "./config.js";
import { isObject, renderId } from "./security.js";

const MAX_BYTES = 2 * 1024 * 1024;
const allowedFiles = new Set(["data.json", "chart.html", "source.txt", "manifest.json"]);
let blobs: BlobServiceClient | undefined;

function container() {
  if (!/^[a-z0-9]{3,24}$/.test(config.storageAccount)) {
    throw new Error("Configure AZURE_STORAGE_ACCOUNT_NAME for Blob artifacts.");
  }
  blobs ??= new BlobServiceClient(
    `https://${config.storageAccount}.blob.core.windows.net`, new DefaultAzureCredential(),
  );
  return blobs.getContainerClient(config.storageContainer);
}

async function privateContainer() {
  const client = container();
  if ((await client.getProperties()).blobPublicAccess) {
    throw new Error("The artifact container must be private.");
  }
  return client;
}

export async function readArtifact(scope: string, id: string, filename: string): Promise<Buffer> {
  renderId.parse(id);
  if (!/^[a-f0-9]{64}$/.test(scope) || !allowedFiles.has(filename)) {
    throw new Error("Invalid artifact reference.");
  }
  const relative = `zodiac/${scope}/${id}/${filename}`;
  if (config.ARTIFACT_STORAGE === "local") {
    const data = await readFile(path.join(config.stateDir, "artifacts", relative));
    if (data.length > MAX_BYTES) throw new Error("Artifact exceeds the size limit.");
    return data;
  }
  const client = await privateContainer();
  const blob = client.getBlobClient(relative);
  const size = (await blob.getProperties()).contentLength;
  if (size === undefined || size > MAX_BYTES) throw new Error("Artifact exceeds the size limit.");
  return blob.downloadToBuffer(0, size);
}

export async function listArtifacts(scope: string): Promise<Record<string, unknown>[]> {
  const ids: string[] = [];
  if (config.ARTIFACT_STORAGE === "local") {
    try {
      const directories = await readdir(path.join(config.stateDir, "artifacts/zodiac", scope), {
        withFileTypes: true,
      });
      for (const item of directories) {
        if (item.isDirectory() && /^[a-f0-9]{32}$/.test(item.name)) ids.push(item.name);
      }
    } catch (error) {
      if (isObject(error) && error.code === "ENOENT") return [];
      throw error;
    }
  } else {
    const client = await privateContainer();
    for await (const blob of client.listBlobsFlat({ prefix: `zodiac/${scope}/` })) {
      const match = /\/([a-f0-9]{32})\/manifest\.json$/.exec(blob.name);
      if (match) ids.push(match[1]);
    }
  }
  const result: Record<string, unknown>[] = [];
  for (const id of ids) {
    let bytes: Buffer;
    try {
      bytes = await readArtifact(scope, id, "manifest.json");
    } catch (error) {
      // Generation publishes manifest.json last; an unfinished directory is not a render.
      if (isObject(error) && error.code === "ENOENT") continue;
      throw error;
    }
    const manifest: unknown = JSON.parse(bytes.toString("utf8"));
    if (!isObject(manifest) || manifest.id !== id || manifest.version !== 1) {
      throw new Error("Invalid astronomical artifact manifest.");
    }
    result.push(manifest);
  }
  return result.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
}

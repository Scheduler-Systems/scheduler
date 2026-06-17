import { createServer } from "node:http";
import { createSchedulerApi, resolveStore } from "./app.mjs";

const port = Number(process.env.PORT ?? 4180);
const host = process.env.HOST ?? "127.0.0.1";

const store = resolveStore();
const app = createSchedulerApi({ store });

const server = createServer(async (incoming, outgoing) => {
  const hasBody = incoming.method !== "GET" && incoming.method !== "HEAD";
  const request = new Request(
    `http://${incoming.headers.host}${incoming.url}`,
    {
      method: incoming.method,
      headers: incoming.headers,
      body: hasBody ? incoming : undefined,
      duplex: hasBody ? "half" : undefined,
    },
  );

  const response = await app(request);
  outgoing.writeHead(
    response.status,
    Object.fromEntries(response.headers.entries()),
  );
  outgoing.end(await response.text());
});

server.listen(port, host, () => {
  const storeType = process.env.SCHEDULER_STORE || "memory";
  console.log(
    `scheduler-api listening on http://${host}:${port} (store: ${storeType})`,
  );
});

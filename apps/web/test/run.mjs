import { run } from "node:test";
import { spec } from "node:test/reporters";
import process from "node:process";

let failed = false;

const stream = run({
  files: [
    "test/scheduleShell.test.mjs",
    "test/api.test.mjs",
    "test/auth.test.mjs",
    "test/authenticated.spec.mjs",
  ],
  concurrency: false,
  timeout: 30000,
  forceExit: true,
});

stream.on("test:fail", () => {
  failed = true;
});
stream.compose(new spec()).pipe(process.stdout);

stream.on("end", () => process.exit(failed ? 1 : 0));

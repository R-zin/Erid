import { execFile } from "node:child_process";
import * as os from "node:os";

/**
 * Resolve the human actor name used for presence entries.
 *
 * Precedence (first non-empty wins):
 *   1. the `actorName` setting (passed in by the caller),
 *   2. `git config user.name` (in `cwd`, the workspace folder),
 *   3. `os.userInfo().username`.
 */
export async function resolveActorName(setting: string | undefined, cwd?: string): Promise<string> {
  const fromSetting = setting?.trim();
  if (fromSetting) {
    return fromSetting;
  }
  const fromGit = await gitUserName(cwd);
  if (fromGit) {
    return fromGit;
  }
  try {
    return os.userInfo().username;
  } catch {
    return "human";
  }
}

/** `git config user.name`, or `undefined` when git is missing, errors, or returns empty. */
export function gitUserName(cwd?: string): Promise<string | undefined> {
  return new Promise((resolve) => {
    execFile("git", ["config", "user.name"], { cwd, timeout: 5000 }, (err, stdout) => {
      if (err) {
        resolve(undefined);
        return;
      }
      const name = stdout.toString().trim();
      resolve(name.length > 0 ? name : undefined);
    });
  });
}

// Runs the Khronos glTF validator (npm package `gltf-validator`) over GLB files
// for tests/test_gltf_validator.py.
//   node gltf_validate.js PACKAGE_DIR LIST_FILE OUT_JSON
// PACKAGE_DIR: a folder whose node_modules holds gltf-validator, or the package
// folder itself.  LIST_FILE: one GLB path per line.  OUT_JSON gets
// [{"file", "issues": [[severity, code, pointer, message]]}] (severity 0 error,
// 1 warning, 2 info, 3 hint) or {"file", "crash"}.
const fs = require('fs');
const path = require('path');
const [pkg, list, out] = process.argv.slice(2);
let validator;
try {
  validator = require(path.join(path.resolve(pkg), 'node_modules', 'gltf-validator'));
} catch (e) {
  validator = require(path.resolve(pkg));
}
const files = fs.readFileSync(list, 'utf8').split('\n').filter(Boolean);
(async () => {
  const res = [];
  for (const f of files) {
    try {
      const r = await validator.validateBytes(new Uint8Array(fs.readFileSync(f)), {
        uri: path.basename(f),
        maxIssues: 1000,
      });
      res.push({
        file: f,
        generator: r.info && r.info.generator,
        issues: r.issues.messages.map((m) => [m.severity, m.code, m.pointer || '', m.message]),
      });
    } catch (e) {
      res.push({ file: f, crash: String(e && e.message ? e.message : e) });
    }
  }
  fs.writeFileSync(out, JSON.stringify(res));
})();

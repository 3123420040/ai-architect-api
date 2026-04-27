import fs from 'node:fs';
import path from 'node:path';
import validator from 'gltf-validator';

const [, , inputPath, reportPath] = process.argv;

if (!inputPath || !reportPath) {
  console.error('Usage: node validate-gltf.mjs <input.glb> <report.json>');
  process.exit(2);
}

const asset = fs.readFileSync(inputPath);
const report = await validator.validateBytes(new Uint8Array(asset), {
  uri: path.basename(inputPath),
  format: inputPath.toLowerCase().endsWith('.glb') ? 'glb' : 'gltf',
  maxIssues: 0,
  severityOverrides: {
    IMAGE_UNRECOGNIZED_FORMAT: 2,
  },
  externalResourceFunction: async (uri) =>
    new Uint8Array(await fs.promises.readFile(path.resolve(path.dirname(inputPath), decodeURIComponent(uri)))),
});

fs.mkdirSync(path.dirname(reportPath), { recursive: true });
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

const issues = report.issues ?? {};
const messages = issues.messages ?? [];
const errors = issues.numErrors ?? 0;
const warnings = messages.filter((message) => message.severity === 1);
const disallowedWarnings = warnings.filter((message) => !String(message.code ?? '').includes('UNUSED'));

if (errors > 0 || disallowedWarnings.length > 0) {
  console.error(
    JSON.stringify(
      {
        errors,
        disallowedWarnings: disallowedWarnings.map((message) => ({
          code: message.code,
          message: message.message,
        })),
      },
      null,
      2,
    ),
  );
  process.exit(1);
}

console.log(
  JSON.stringify({
    status: 'pass',
    errors,
    warnings: warnings.length,
  }),
);

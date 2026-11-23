const { spawnSync } = require("child_process");
const path = require("path");

const rootDir = path.resolve(__dirname, "..");
const samples = [
  "dimension_detail.json",
  "emotion_stress_detail.json",
  "personality_detail.json",
  "cognitive_growth_detail.json",
];

const outputDir = path.join(rootDir, "output", "theme_samples");

for (const sample of samples) {
  const layoutPath = path.join(rootDir, "layout_samples", sample);
  const result = spawnSync(
    process.execPath,
    [path.join(rootDir, "renderer", "render_layout.js"), layoutPath, outputDir],
    {
      cwd: rootDir,
      stdio: "inherit",
    }
  );

  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

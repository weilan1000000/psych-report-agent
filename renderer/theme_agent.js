const fs = require("fs");
const path = require("path");

const rootDir = path.resolve(__dirname, "..");
const themesDir = path.join(rootDir, "config", "themes");
const fallbackThemeName = "calm_blue_teal";

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function listThemes() {
  return fs
    .readdirSync(themesDir)
    .filter((file) => file.endsWith(".json"))
    .map((file) => readJson(path.join(themesDir, file)));
}

function loadTheme(themeName) {
  const themePath = path.join(themesDir, `${themeName}.json`);
  if (!fs.existsSync(themePath)) {
    throw new Error(`Theme not found: ${themeName}`);
  }
  return readJson(themePath);
}

function selectTheme(layout, explicitThemeName) {
  if (explicitThemeName) return loadTheme(explicitThemeName);
  if (layout.theme) return loadTheme(layout.theme);

  const reportType = String(layout.report_type || layout.reportType || "").toLowerCase();
  const themes = listThemes();
  const matched = themes.find((theme) =>
    (theme.best_for || []).some((item) => String(item).toLowerCase() === reportType)
  );

  return matched || loadTheme(fallbackThemeName);
}

module.exports = {
  fallbackThemeName,
  listThemes,
  loadTheme,
  selectTheme,
};

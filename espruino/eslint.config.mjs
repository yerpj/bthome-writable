// Espruino runs an ES5-era interpreter with a few ES6 conveniences (let/const,
// arrow functions, template literals). Lint the module accordingly: no modules,
// no async. Tests run under Node, config files are ESM.
export default [
  {
    files: ["*.js", "examples/**/*.js"],
    languageOptions: {
      ecmaVersion: 2015,
      sourceType: "script",
      globals: {
        // Espruino globals used by the module.
        NRF: "readonly",
        E: "readonly",
        Storage: "readonly",
        require: "readonly",
        module: "writable",
        exports: "writable",
        console: "readonly",
        Date: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        digitalWrite: "readonly",
        LED1: "readonly",
        LED2: "readonly",
        LED3: "readonly",
        Puck: "readonly",
        g: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-undef": "error",
      eqeqeq: ["error", "smart"],
    },
  },
  {
    files: ["test/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: { console: "readonly", process: "readonly" },
    },
  },
  {
    files: ["**/*.mjs"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module" },
  },
];

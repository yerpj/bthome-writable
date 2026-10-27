// Espruino runs an ES5-era interpreter with a few ES6 conveniences (let/const,
// arrow functions, template literals). Lint the module accordingly: no modules,
// no async. Tests run under Node, config files are ESM.
export default [
  {
    files: ["*.js", "examples/**/*.js", "bench/**/*.js"],
    languageOptions: {
      ecmaVersion: 2015,
      sourceType: "script",
      globals: {
        // Espruino globals used by the module.
        NRF: "readonly",
        AES: "readonly",
        E: "readonly",
        Storage: "readonly",
        require: "readonly",
        module: "writable",
        exports: "writable",
        console: "readonly",
        getTime: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        // bench/ only: a repro sketch drives itself from a timer and hangs its
        // console handles off `global`, which no example needs.
        setInterval: "readonly",
        clearInterval: "readonly",
        global: "readonly",
        digitalWrite: "readonly",
        analogWrite: "readonly",
        LED1: "readonly",
        LED2: "readonly",
        LED3: "readonly",
        I2C: "readonly",
        D1: "readonly",
        D2: "readonly",
        D29: "readonly",
        D45: "readonly",
        D47: "readonly",
        Puck: "readonly",
        setWatch: "readonly",
        BTN: "readonly",
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

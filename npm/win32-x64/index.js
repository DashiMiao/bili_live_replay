"use strict";
const path = require("path");
const exe = process.platform === "win32" ? ".exe" : "";
module.exports = path.join(__dirname, "bin", "bili_live_replay" + exe);

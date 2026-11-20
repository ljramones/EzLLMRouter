"use strict";
// Regression subprocess guard; not a sandbox for adversarial/native test code.
const mode = process.env.EZLLMROUTER_TEST_NETWORK;
if (mode) {
  const net = require("node:net");
  const dns = require("node:dns");
  const dgram = require("node:dgram");
  const denied = () => { throw new Error("network operation in regression subprocess"); };
  const local = host => host === "localhost" || host === "::1" || host === "[::1]" || (net.isIP(host) === 4 && host.startsWith("127."));

  for (const object of [dns, dns.promises]) {
    for (const name of Object.keys(object)) {
      if (/^(?:resolve|reverse|lookupService)/u.test(name)) object[name] = denied;
    }
    // Custom resolvers must not bypass the module's guarded DNS methods.
    object.Resolver = class { constructor() { denied(); } };
  }
  for (const name of ["connect", "bind", "send"]) dgram.Socket.prototype[name] = denied;

  if (mode === "offline") {
    for (const name of ["connect", "createConnection"]) net[name] = denied;
    net.Socket.prototype.connect = denied;
    net.Server.prototype.listen = denied;
    dns.lookup = denied;
    dns.promises.lookup = denied;
    globalThis.fetch = denied;
    if (globalThis.WebSocket) globalThis.WebSocket = class { constructor() { denied(); } };
    require("node:tls").connect = denied;

    // Native helpers cannot inherit JS hooks. Python owns the audited tooling
    // and child-interpreter gate; offline Node fixtures do not launch commands.
    const child = require("node:child_process");
    for (const name of ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]) {
      child[name] = denied;
    }
  } else {
    for (const [object, name] of [[net.Socket.prototype, "connect"], [net.Server.prototype, "listen"]]) {
      const original = object[name];
      object[name] = function (...args) {
        const values = Array.isArray(args[0]) ? args[0] : args;
        const options = typeof values[0] === "object" ? values[0] : {
          port: values[0], host: typeof values[1] === "string" ? values[1] : undefined,
        };
        if (!options.path && !local(options.host || options.hostname || (name === "connect" ? "localhost" : ""))) denied();
        return original.apply(this, args);
      };
    }
    for (const object of [dns, dns.promises]) {
      const lookup = object.lookup;
      object.lookup = function (host, ...args) {
        if (!local(host)) denied();
        return lookup.call(this, host, ...args);
      };
    }
    const fetch = globalThis.fetch;
    globalThis.fetch = (url, options) => {
      const target = new URL(typeof url === "object" && url.url ? url.url : url);
      if (!local(target.hostname)) denied();
      return fetch(url, options);
    };
  }
}

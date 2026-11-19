import client = require("@cognitivedynamics/ezllmrouter-client");
const instance = new client.EzLLMRouterClient({ baseUrl: "http://synthetic.invalid", token: "synthetic-token" });
const capabilities: Promise<client.Wire02.CapabilityResponse> = instance.getCapabilities();
const version: "0.2" = client.contractVersion;
void [capabilities, version];

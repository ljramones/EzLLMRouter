import client from "./index.cjs";

export const {
  EzLLMRouterClient, EzLLMRouterError, IntegrationClient, IntegrationClientError,
  DurankiClient, DurankiError, contractVersion,
} = client;
export default client;

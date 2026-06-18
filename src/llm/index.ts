import { LlmProvider, LlmConfig, LlmMessage } from '../types';

/**
 * Creates an LLM provider based on configuration.
 */
export function createLlmProvider(config: LlmConfig): LlmProvider {
  switch (config.provider) {
    case 'openai':
      return new OpenAIProvider(config);
    case 'azure-openai':
      return new AzureOpenAIProvider(config);
    case 'anthropic':
      return new AnthropicProvider(config);
    case 'gemini':
      return new GeminiProvider(config);
    default:
      throw new Error(`Unsupported LLM provider: ${config.provider}`);
  }
}

/**
 * Base class with common HTTP request logic.
 */
abstract class BaseLlmProvider implements LlmProvider {
  abstract name: string;

  constructor(protected config: LlmConfig) {}

  abstract analyze(prompt: string, context?: Record<string, string>): Promise<string>;

  protected buildMessages(prompt: string, context?: Record<string, string>): LlmMessage[] {
    const systemMessage = `You are an expert test automation engineer specializing in Playwright. 
You analyze test failures and DOM snapshots to identify the correct locators for elements.
You provide precise, actionable suggestions for fixing broken selectors.
Always prefer robust locator strategies in this order: role-based > test-id > text > CSS > XPath.`;

    let userContent = prompt;
    if (context) {
      userContent += '\n\n--- Additional Context ---\n';
      for (const [key, value] of Object.entries(context)) {
        userContent += `\n### ${key}:\n${value}\n`;
      }
    }

    return [
      { role: 'system', content: systemMessage },
      { role: 'user', content: userContent },
    ];
  }

  protected async httpPost(url: string, body: unknown, headers: Record<string, string>): Promise<unknown> {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`LLM API error (${response.status}): ${errorText}`);
    }

    return response.json();
  }
}

// --- OpenAI Provider ---

class OpenAIProvider extends BaseLlmProvider {
  name = 'openai';

  async analyze(prompt: string, context?: Record<string, string>): Promise<string> {
    const messages = this.buildMessages(prompt, context);
    const model = this.config.model || 'gpt-4o';

    const response = await this.httpPost(
      'https://api.openai.com/v1/chat/completions',
      {
        model,
        messages,
        temperature: this.config.temperature ?? 0.2,
        max_tokens: this.config.maxTokens ?? 4096,
      },
      { Authorization: `Bearer ${this.config.apiKey}` }
    ) as { choices: Array<{ message: { content: string } }> };

    return response.choices[0]?.message?.content || '';
  }
}

// --- Azure OpenAI Provider ---

class AzureOpenAIProvider extends BaseLlmProvider {
  name = 'azure-openai';

  async analyze(prompt: string, context?: Record<string, string>): Promise<string> {
    const messages = this.buildMessages(prompt, context);
    const endpoint = this.config.endpoint;
    const deployment = this.config.deployment;
    const apiVersion = this.config.apiVersion || '2024-02-01';

    if (!endpoint || !deployment) {
      throw new Error('Azure OpenAI requires endpoint and deployment configuration');
    }

    const url = `${endpoint}/openai/deployments/${deployment}/chat/completions?api-version=${apiVersion}`;

    const response = await this.httpPost(
      url,
      {
        messages,
        temperature: this.config.temperature ?? 0.2,
        max_tokens: this.config.maxTokens ?? 4096,
      },
      { 'api-key': this.config.apiKey }
    ) as { choices: Array<{ message: { content: string } }> };

    return response.choices[0]?.message?.content || '';
  }
}

// --- Anthropic Provider ---

class AnthropicProvider extends BaseLlmProvider {
  name = 'anthropic';

  async analyze(prompt: string, context?: Record<string, string>): Promise<string> {
    const messages = this.buildMessages(prompt, context);
    const model = this.config.model || 'claude-sonnet-4-20250514';

    // Anthropic uses separate system parameter
    const systemMsg = messages.find(m => m.role === 'system')?.content || '';
    const userMessages = messages.filter(m => m.role !== 'system');

    const response = await this.httpPost(
      'https://api.anthropic.com/v1/messages',
      {
        model,
        system: systemMsg,
        messages: userMessages,
        max_tokens: this.config.maxTokens ?? 4096,
        temperature: this.config.temperature ?? 0.2,
      },
      {
        'x-api-key': this.config.apiKey,
        'anthropic-version': '2023-06-01',
      }
    ) as { content: Array<{ text: string }> };

    return response.content[0]?.text || '';
  }
}

// --- Google Gemini Provider ---

class GeminiProvider extends BaseLlmProvider {
  name = 'gemini';

  async analyze(prompt: string, context?: Record<string, string>): Promise<string> {
    const messages = this.buildMessages(prompt, context);
    const model = this.config.model || 'gemini-1.5-pro';

    const systemMsg = messages.find(m => m.role === 'system')?.content || '';
    const userMsg = messages.find(m => m.role === 'user')?.content || '';

    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${this.config.apiKey}`;

    const response = await this.httpPost(
      url,
      {
        system_instruction: { parts: [{ text: systemMsg }] },
        contents: [{ parts: [{ text: userMsg }] }],
        generationConfig: {
          temperature: this.config.temperature ?? 0.2,
          maxOutputTokens: this.config.maxTokens ?? 4096,
        },
      },
      {}
    ) as { candidates: Array<{ content: { parts: Array<{ text: string }> } }> };

    return response.candidates[0]?.content?.parts[0]?.text || '';
  }
}

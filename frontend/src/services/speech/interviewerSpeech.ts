import type { ChatMessage } from "../../model/types";

export interface SpeechState {
	enabled: boolean;
	available: boolean;
	speaking: boolean;
	busy: boolean;
	error: string | null;
}

// Short utterances avoid long-message stalls in browser speech engines.
export function speechChunks(text: string): string[] {
	const words = text.replace(/[`*_#]/g, "").trim().split(/\s+/).filter(Boolean);
	const chunks: string[] = [];
	let chunk = "";
	for (const word of words) {
		if (chunk && chunk.length + 1 + word.length > 180) {
			chunks.push(chunk);
			chunk = "";
		}
		chunk += (chunk ? " " : "") + word;
		if (/[.!?…]$/.test(word)) {
			chunks.push(chunk);
			chunk = "";
		}
	}
	if (chunk) chunks.push(chunk);
	return chunks;
}

/** Owns one interview's speech queue. Message IDs survive repeated HTTP/WS snapshots. */
export class InterviewerSpeech {
	private state: SpeechState;
	private seen = new Set<string>();
	private messages: ChatMessage[] = [];
	private queue: string[] = [];
	private active: SpeechSynthesisUtterance | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private voice: SpeechSynthesisVoice | undefined;
	private listeners = new Set<() => void>();

	private synth: SpeechSynthesis | null;
	private utterance: (text: string) => SpeechSynthesisUtterance;

	constructor(
		synth: SpeechSynthesis | null,
		utterance: (text: string) => SpeechSynthesisUtterance,
	) {
		this.synth = synth;
		this.utterance = utterance;
		this.state = { enabled: false, available: false, speaking: false, busy: false, error: null };
	}

	getSnapshot = () => this.state;
	subscribe = (listener: () => void) => {
		this.listeners.add(listener);
		return () => { this.listeners.delete(listener); };
	};
	private emit(update: Partial<SpeechState>) {
		this.state = { ...this.state, ...update };
		this.listeners.forEach(listener => listener());
	}

	refreshVoices = () => {
		const russian = this.synth?.getVoices().filter(v => /^ru(?:[-_]|$)/i.test(v.lang)) ?? [];
		this.voice = russian.find(v => v.localService) ?? russian[0];
		this.emit({ available: Boolean(this.voice) });
	};

	connect() {
		this.refreshVoices();
		this.synth?.addEventListener("voiceschanged", this.refreshVoices);
		return () => {
			this.synth?.removeEventListener("voiceschanged", this.refreshVoices);
			this.stop();
		};
	}

	private aiMessages() {
		return this.messages.filter(m => m.authorKind === "ai" && m.text.trim());
	}

	// Read during render as well, so an ended snapshot cannot unmount the final feedback.
	hasUnread(messages: ChatMessage[]) {
		return this.state.enabled && messages.some(m => m.authorKind === "ai" && m.text.trim() && !this.seen.has(m.id));
	}

	update(messages: ChatMessage[]) {
		this.messages = messages;
		if (!this.state.enabled) return;
		for (const message of this.aiMessages()) {
			if (this.seen.has(message.id)) continue;
			this.seen.add(message.id);
			this.queue.push(...speechChunks(message.text));
		}
		this.pump();
	}

	// Called from a user click to meet browser audio activation requirements.
	enable = () => {
		this.refreshVoices();
		if (!this.synth || !this.voice) return;
		this.emit({ enabled: true, error: null });
		// Enabling mid-interview reads the latest remark, not the entire transcript.
		const messages = this.aiMessages();
		messages.slice(0, -1).forEach(m => this.seen.add(m.id));
		const latest = messages[messages.length - 1];
		if (latest) this.seen.delete(latest.id);
		this.update(this.messages);
	};

	private cancelQueue() {
		clearTimeout(this.timer);
		const active = this.active;
		this.active = null;
		this.queue = [];
		if (active) {
			active.onstart = active.onend = active.onerror = null;
			this.synth?.cancel();
		}
	}

	stop = () => {
		this.cancelQueue();
		this.emit({ enabled: false, speaking: false, busy: false });
	};

	repeat = () => {
		this.cancelQueue();
		this.emit({ speaking: false, busy: false });
		this.enable();
	};

	private fail(message: string) {
		this.cancelQueue();
		this.emit({ enabled: false, speaking: false, busy: false, error: message });
	}

	private pump() {
		if (this.active || !this.state.enabled) return;
		const text = this.queue.shift();
		if (!text) {
			this.emit({ busy: false, speaking: false });
			return;
		}
		if (!this.synth || !this.voice) {
			this.fail("Русский голос недоступен. Можно продолжить в чате.");
			return;
		}
		const utterance = this.utterance(text);
		utterance.lang = this.voice.lang;
		utterance.voice = this.voice;
		utterance.rate = 1;
		this.active = utterance;
		this.emit({ busy: true });
		const fail = () => this.fail("Не удалось воспроизвести речь. Нажми «Включить голос» ещё раз или продолжи в чате.");
		utterance.onstart = () => {
			if (this.active !== utterance) return;
			clearTimeout(this.timer);
			this.emit({ speaking: true });
			this.timer = setTimeout(fail, 45000);
		};
		utterance.onend = () => {
			if (this.active !== utterance) return;
			clearTimeout(this.timer);
			this.active = null;
			this.emit({ speaking: false });
			this.pump();
		};
		utterance.onerror = () => { if (this.active === utterance) fail(); };
		this.timer = setTimeout(fail, 12000);
		try { this.synth.speak(utterance); } catch { fail(); }
	}
}

import type { ChatMessage } from "../../model/types";

export interface SpeechState {
	enabled: boolean;
	available: boolean;
	speaking: boolean;
	busy: boolean;
	error: string | null;
}

export interface SpeechPlayer {
	unlock(): Promise<void>;
	play(
		data: ArrayBuffer,
		signal: AbortSignal,
		onPlaying: (playing: boolean) => void,
	): Promise<void>;
	stop(): void;
	dispose(): void;
}

export type AudioLoader = (
	message: ChatMessage,
	signal: AbortSignal,
) => Promise<ArrayBuffer>;

export class InterviewerSpeech {
	private state: SpeechState;
	private seen = new Set<string>();
	private messages: ChatMessage[] = [];
	private queue: ChatMessage[] = [];
	private active: AbortController | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private ready: Promise<void> = Promise.resolve();
	private listeners = new Set<() => void>();
	private player: SpeechPlayer | null;
	private load: AudioLoader;

	constructor(player: SpeechPlayer | null, load: AudioLoader) {
		this.player = player;
		this.load = load;
		this.state = {
			enabled: false,
			available: Boolean(player),
			speaking: false,
			busy: false,
			error: null,
		};
	}

	getSnapshot = () => this.state;
	subscribe = (listener: () => void) => {
		this.listeners.add(listener);
		return () => {
			this.listeners.delete(listener);
		};
	};
	private emit(update: Partial<SpeechState>) {
		this.state = { ...this.state, ...update };
		this.listeners.forEach((listener) => listener());
	}

	connect() {
		return () => {
			this.stop();
			this.player?.dispose();
		};
	}

	private aiMessages() {
		return this.messages.filter(
			(m) => m.authorKind === "ai" && m.text.trim(),
		);
	}

	hasUnread(messages: ChatMessage[]) {
		return (
			this.state.enabled &&
			messages.some(
				(m) =>
					m.authorKind === "ai" &&
					m.text.trim() &&
					!this.seen.has(m.id),
			)
		);
	}

	update(messages: ChatMessage[]) {
		this.messages = messages;
		if (!this.state.enabled) return;
		for (const message of this.aiMessages()) {
			if (this.seen.has(message.id)) continue;
			this.seen.add(message.id);
			this.queue.push(message);
		}
		void this.pump();
	}

	enable = () => {
		if (!this.player || this.state.enabled) return;
		this.ready = this.player.unlock();
		void this.ready.catch(() => {});
		this.emit({ enabled: true, error: null });
		const messages = this.aiMessages();
		messages.slice(0, -1).forEach((m) => this.seen.add(m.id));
		const latest = messages[messages.length - 1];
		if (latest) this.seen.delete(latest.id);
		this.update(this.messages);
	};

	stop = () => {
		clearTimeout(this.timer);
		this.active?.abort();
		this.active = null;
		this.queue = [];
		this.player?.stop();
		this.emit({ enabled: false, speaking: false, busy: false });
	};

	repeat = () => {
		this.stop();
		this.enable();
	};

	private async pump() {
		if (this.active || !this.state.enabled || !this.player) return;
		const message = this.queue.shift();
		if (!message) {
			this.emit({ busy: false, speaking: false });
			return;
		}
		const operation = new AbortController();
		this.active = operation;
		this.emit({ busy: true, speaking: false });
		const timeout = setTimeout(() => {
			if (this.active !== operation) return;
			this.stop();
			this.emit({
				error: "Голос готовится слишком долго. Попробуй ещё раз или продолжи в чате.",
			});
		}, 120000);
		this.timer = timeout;
		try {
			await this.ready;
			if (operation.signal.aborted) return;
			const audio = await this.load(message, operation.signal);
			clearTimeout(timeout);
			if (this.active !== operation || operation.signal.aborted) return;
			await this.player.play(audio, operation.signal, (speaking) => {
				if (this.active === operation) this.emit({ speaking });
			});
			if (this.active !== operation) return;
			this.active = null;
			this.emit({ speaking: false });
			void this.pump();
		} catch (error) {
			if (this.active !== operation) return;
			this.stop();
			this.emit({
				error:
					error instanceof Error
						? error.message
						: "Не удалось озвучить реплику. Попробуй ещё раз.",
			});
		} finally {
			clearTimeout(timeout);
		}
	}
}

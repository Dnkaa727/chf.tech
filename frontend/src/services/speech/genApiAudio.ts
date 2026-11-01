import type { ChatMessage } from "../../model/types";
import type { SpeechPlayer } from "./interviewerSpeech";

export async function loadInterviewAudio(
	message: ChatMessage,
	signal: AbortSignal,
): Promise<ArrayBuffer> {
	if (!message.audioUrl)
		throw new Error(
			"Озвучивание этой реплики недоступно. Продолжи в чате.",
		);
	let response: Response;
	try {
		response = await fetch(message.audioUrl, { method: "POST", signal });
	} catch (error) {
		if (signal.aborted) throw error;
		throw new Error(
			"Нет связи с озвучиванием. Проверь соединение и попробуй ещё раз.",
		);
	}
	if (!response.ok) {
		let detail =
			"Не удалось получить озвучивание. Попробуй ещё раз или продолжи в чате.";
		try {
			const body = await response.json();
			if (typeof body.detail === "string") detail = body.detail;
		} catch {}
		throw new Error(detail);
	}
	if (!response.headers.get("content-type")?.startsWith("audio/")) {
		throw new Error("Сервис озвучивания вернул некорректное аудио.");
	}
	return response.arrayBuffer();
}

export class BrowserAudioPlayer implements SpeechPlayer {
	private context: AudioContext | null = null;
	private cancel: (() => void) | null = null;

	async unlock() {
		if (!this.context || this.context.state === "closed")
			this.context = new AudioContext();
		try {
			await this.context.resume();
		} catch {
			throw new Error(
				"Браузер не разрешил звук. Нажми «Включить голос» ещё раз.",
			);
		}
	}

	async play(
		data: ArrayBuffer,
		signal: AbortSignal,
		onPlaying: (playing: boolean) => void,
	) {
		const context = this.context;
		if (!context)
			throw new Error("Нажми «Включить голос», чтобы разрешить звук.");
		let buffer: AudioBuffer;
		try {
			buffer = await context.decodeAudioData(data);
		} catch {
			throw new Error(
				"Не удалось прочитать аудио. Попробуй озвучить реплику ещё раз.",
			);
		}
		if (signal.aborted) return;
		if (context.state !== "running")
			throw new Error(
				"Звук приостановлен браузером. Нажми «Включить голос» ещё раз.",
			);
		await new Promise<void>((resolve, reject) => {
			const source = context.createBufferSource();
			source.buffer = buffer;
			source.connect(context.destination);
			let finished = false;
			const stateChanged = () => onPlaying(context.state === "running");
			const finish = (error?: Error) => {
				if (finished) return;
				finished = true;
				clearTimeout(timer);
				signal.removeEventListener("abort", abort);
				context.removeEventListener("statechange", stateChanged);
				source.onended = null;
				try {
					source.stop();
				} catch {}
				source.disconnect();
				this.cancel = null;
				onPlaying(false);
				if (error) reject(error);
				else resolve();
			};
			const abort = () => finish();
			const timer = setTimeout(
				() =>
					finish(
						new Error(
							"Воспроизведение остановилось. Попробуй ещё раз.",
						),
					),
				(buffer.duration + 15) * 1000,
			);
			this.cancel = abort;
			signal.addEventListener("abort", abort, { once: true });
			context.addEventListener("statechange", stateChanged);
			source.onended = () => finish();
			try {
				source.start();
				onPlaying(true);
			} catch {
				finish(
					new Error("Не удалось включить звук. Попробуй ещё раз."),
				);
			}
		});
	}

	stop() {
		this.cancel?.();
	}
	dispose() {
		this.stop();
		void this.context?.close().catch(() => {});
		this.context = null;
	}
}

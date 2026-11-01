import { useEffect, useState, useSyncExternalStore } from "react";
import type { ChatMessage } from "../model/types";
import { InterviewerSpeech } from "../services/speech/interviewerSpeech";

export function useInterviewerSpeech(messages: ChatMessage[]) {
	const supported = typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
	const [controller] = useState(() => new InterviewerSpeech(
		supported ? window.speechSynthesis : null,
		text => new SpeechSynthesisUtterance(text),
	));
	const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
	useEffect(() => controller.connect(), [controller]);
	useEffect(() => controller.update(messages), [controller, messages]);
	return {
		...state,
		supported,
		hasUnread: controller.hasUnread(messages),
		enable: controller.enable,
		stop: controller.stop,
		repeat: controller.repeat,
	};
}

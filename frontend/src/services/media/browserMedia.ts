import { createStore } from "../store";
import type { MediaService } from "../types";
import type { MediaState } from "../../model/types";

export function createBrowserMediaService(): MediaService {
	const devices = createStore<MediaState>({ camera: "off", mic: "off" });
	const local = new MediaStream();
	const localStream = createStore<MediaStream>(local);
	const tracks: Partial<Record<"camera" | "mic", MediaStreamTrack>> = {};

	async function toggle(kind: "camera" | "mic", on: boolean) {
		const patch = (s: MediaState["camera"]) =>
			devices.set({ ...devices.get(), [kind]: s });

		if (!on) {

			const t = tracks[kind];
			if (t) {
				t.stop();
				local.removeTrack(t);
				delete tracks[kind];
			}

			patch("off");
			return;
		}

		try {
			const s = await navigator.mediaDevices.getUserMedia(
				kind === "camera" ? { video: true } : { audio: true },
			);
			const t =
				kind === "camera" ? s.getVideoTracks()[0] : s.getAudioTracks()[0];
			tracks[kind] = t;
			local.addTrack(t);
			patch("on");
		} catch {
			patch("denied");
		}
	}

	return {
		devices,
		localStream,
		setCamera: (on) => toggle("camera", on),
		setMic: (on) => toggle("mic", on),
	};
}

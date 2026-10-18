import { useServices } from "../services/context";
import { useReadable } from "./useReadable";

export function useMediaControls() {
	const { media } = useServices();
	const devices = useReadable(media.devices);

	return {
		devices,
		toggleCamera: () => void media.setCamera(devices.camera !== "on"),
		toggleMic: () => void media.setMic(devices.mic !== "on"),
	};
}

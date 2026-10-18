import { useState, type ReactNode } from "react";
import { useServices } from "./services/context";
import { PreparePage } from "./pages/PreparePage";
import { ConferencePage } from "./pages/ConferencePage";
import { FinishedPage } from "./pages/FinishedPage";
import { library } from '@fortawesome/fontawesome-svg-core';
import { fas } from '@fortawesome/free-solid-svg-icons';
import "./styles/main.scss";

library.add(fas);

type ScreenId = "prepare" | "conference" | "finished";

export function App() {
	const s = useServices();
	const [screen, setScreen] = useState<ScreenId>("prepare");
	const finish = () => {
		void s.media.setCamera(false);
		void s.media.setMic(false);
		setScreen("finished");
	};

	const screens: Record<ScreenId, () => ReactNode> = {
		prepare: () => (
			<PreparePage
				onJoin={(name) => {
					void s.conference.join(name);
					setScreen("conference");
				}}
			/>
		),
		conference: () => <ConferencePage onLeave={finish} />,
		finished: () => <FinishedPage onRestart={() => setScreen("prepare")} />,
	};
	return <>{screens[screen]()}</>;
}

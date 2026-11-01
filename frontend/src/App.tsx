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
	const [error, setError] = useState<string | null>(null);
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
					setError(null);
                    void s.conference.join(name).then(() => setScreen("conference")).catch(e => setError(e instanceof Error ? e.message : "Не удалось подключиться"));
				}}
			/>
		),
		conference: () => <ConferencePage onLeave={finish} />,
		finished: () => <FinishedPage onRestart={() => setScreen("prepare")} />,
	};
	return <>{error && <p role="alert">{error}</p>}{screens[screen]()}</>;
}

import { useEffect, useRef, type ReactNode } from "react";
import type { StageContent } from "../../model/types";

type Renderer<T extends StageContent> = (content: T) => ReactNode;

function VideoView(props: { stream: MediaStream }) {
	const { stream } = props;
	const ref = useRef<HTMLVideoElement>(null);

	useEffect(() => {
		if (ref.current)
			ref.current.srcObject = stream;
	}, [stream]);

	return <video ref={ref} className="stage-video" autoPlay muted playsInline />;
}

function Visualizer(props: { level: number }) {
	const { level } = props;

	return (
		<div className="stage-viz" aria-hidden>
			{Array.from({ length: 17 }, (_, i) => (
				<i
					key={i}
					style={{
						height: `${8 + level * 72 * Math.abs(Math.sin(i * 1.7 + level * 9))}%`,
					}}
				/>
			))}
		</div>
	);
}

/* TODO: Вообще переписать это всё  */
const renderers: {
	[K in StageContent["type"]]: Renderer<Extract<StageContent, { type: K }>>;
} = {
	avatar: () => null,
	image: (c) => <img className="stage-image" src={c.src} alt={c.alt ?? ""} />,
	video: (c) => <VideoView stream={c.stream} />,
	visualizer: (c) => <Visualizer level={c.level} />,
};

export function StageContentView(props: { content: StageContent }) {
	const render = renderers[props.content.type] as Renderer<StageContent>;
	return <>{render(props.content)}</>;
}

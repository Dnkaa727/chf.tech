export interface PageIntroProps {
	title: string;
	text?: string;
}

export function PageIntro(props: PageIntroProps) {
	const { title, text } = props;

	return (
		<div className="intro">
			<h1 className="intro__title">{title}</h1>
			{text && <p className="intro__text">{text}</p>}
		</div>
	);
}

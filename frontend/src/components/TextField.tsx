import { classes } from "./classes";

export interface TextFieldProps {
	id: string;
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	hint?: string;
	error?: string;
	prefix?: string;
	autoFocus?: boolean;
	onSubmit?: () => void;
}

export function TextField(props: TextFieldProps) {
	const {
		id,
		value,
		onChange,
		placeholder,
		hint,
		error,
		prefix,
		autoFocus,
		onSubmit,
	} = props;

	return (
		<div className="field">
			<div className={classes("field__box", !!error && "field__box--error")}>
				{prefix && <span className="field__prefix">{prefix}</span>}
				<input
					id={id}
					className="field__input"
					value={value}
					placeholder={placeholder}
					autoFocus={autoFocus}
					onChange={(e) => onChange(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter") onSubmit?.();
					}}
				/>
			</div>
			{(error || hint) && (
				<p className={classes("field__hint", !!error && "field__hint--error")}>
					{error ?? hint}
				</p>
			)}
		</div>
	);
}

import React, { useCallback, useRef } from 'react';

interface ResizableHeaderCellProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
    width?: number;
    minWidth?: number;
    maxWidth?: number;
    onResize?: (nextWidth: number) => void;
}

const ResizableHeaderCell: React.FC<ResizableHeaderCellProps> = ({
    width,
    minWidth = 90,
    maxWidth = 960,
    onResize,
    children,
    className,
    style,
    ...rest
}) => {
    const startXRef = useRef(0);
    const startWidthRef = useRef(width ?? minWidth);

    const handleMouseDown = useCallback(
        (event: React.MouseEvent<HTMLSpanElement>) => {
            if (!onResize) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();

            startXRef.current = event.clientX;
            startWidthRef.current = width ?? minWidth;

            const previousUserSelect = document.body.style.userSelect;
            document.body.style.userSelect = 'none';

            const handleMouseMove = (moveEvent: MouseEvent) => {
                const delta = moveEvent.clientX - startXRef.current;
                const nextWidth = Math.max(minWidth, Math.min(maxWidth, startWidthRef.current + delta));
                onResize(nextWidth);
            };

            const handleMouseUp = () => {
                document.body.style.userSelect = previousUserSelect;
                document.removeEventListener('mousemove', handleMouseMove);
                document.removeEventListener('mouseup', handleMouseUp);
            };

            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        },
        [maxWidth, minWidth, onResize, width]
    );

    return (
        <th
            {...rest}
            className={className}
            style={width ? { ...style, width } : style}
        >
            <div className={`resizable-th ${onResize ? 'resizable-th--active' : ''}`}>
                <div className="resizable-th__content">{children}</div>
                {onResize && (
                    <span
                        className="resizable-th__handle"
                        onMouseDown={handleMouseDown}
                        role="separator"
                        aria-orientation="vertical"
                        aria-label="调整列宽"
                    />
                )}
            </div>
        </th>
    );
};

export default ResizableHeaderCell;

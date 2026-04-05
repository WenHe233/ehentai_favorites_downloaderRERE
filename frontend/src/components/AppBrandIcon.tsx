import React from 'react';

interface AppBrandIconProps {
    size?: number;
    className?: string;
}

const AppBrandIcon: React.FC<AppBrandIconProps> = ({ size = 52, className }) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
    >
        <rect x="4" y="4" width="56" height="56" rx="18" fill="#3F67EA" />
        <rect x="14" y="12" width="36" height="22" rx="8" fill="#F4F7FF" />
        <rect x="14" y="12" width="36" height="22" rx="8" stroke="#C8D5FF" />

        <path
            d="M20 17.5C20 16.12 21.12 15 22.5 15H28.5C29.88 15 31 16.12 31 17.5V28.2C31 28.83 30.29 29.2 29.77 28.84L25.5 25.9L21.23 28.84C20.71 29.2 20 28.83 20 28.2V17.5Z"
            fill="#2D50C8"
        />
        <path d="M35 19.5H44" stroke="#6D8FF2" strokeWidth="2.4" strokeLinecap="round" />
        <path d="M35 24.5H42" stroke="#9CB3F8" strokeWidth="2.4" strokeLinecap="round" />

        <path d="M32 36.8V40.6" stroke="#B9CBFF" strokeWidth="4.6" strokeLinecap="round" />
        <path
            d="M29.6 39.4L32 41.8L34.4 39.4"
            stroke="#B9CBFF"
            strokeWidth="4.6"
            strokeLinecap="round"
            strokeLinejoin="round"
        />
        <path d="M32 36.8V40.6" stroke="#FFFFFF" strokeWidth="2.8" strokeLinecap="round" />
        <path
            d="M29.6 39.4L32 41.8L34.4 39.4"
            stroke="#FFFFFF"
            strokeWidth="2.8"
            strokeLinecap="round"
            strokeLinejoin="round"
        />

        <path
            d="M19 44H25L28 47H36L39 44H45C46.1 44 47 44.9 47 46V48.5C47 50.43 45.43 52 43.5 52H20.5C18.57 52 17 50.43 17 48.5V46C17 44.9 17.9 44 19 44Z"
            fill="#18357F"
        />
        <path d="M19 44H25L28 47H36L39 44H45" stroke="#B9CBFF" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
);

export default AppBrandIcon;

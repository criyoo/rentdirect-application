import { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import Footer from './Footer'
import Navbar from './Navbar'

interface AdminRouteWrapperProps {
    children: ReactNode
}

export default function AdminRouteWrapper({ children }: AdminRouteWrapperProps) {
    const location = useLocation()

    // Don't show navbar for admin routes
    const isAdminRoute = location.pathname.startsWith('/admin')

    return (
        <div className="min-h-screen bg-gray-50 flex flex-col">
            {!isAdminRoute && <Navbar />}
            <main className="flex-1">
                {children}
            </main>
            {!isAdminRoute && <Footer />}
        </div>
    )
}

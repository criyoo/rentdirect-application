import { Link } from 'react-router-dom'
import { HiChatAlt2, HiMail, HiPhone, HiSupport } from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { landlordSupportFaqs, tenantSupportContacts, tenantSupportFaqs } from '@/lib/tenantSupport'

export default function TenantSupportPage() {
    const { user } = useAuth()
    const role = user?.role === 'landlord' ? 'landlord' : 'tenant'
    const dashboardPath = user?.id ? `/dashboard/${role}/${user.id}` : '/'
    const faqs = role === 'landlord' ? landlordSupportFaqs : tenantSupportFaqs

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-5xl">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Support</p>
                        <h1 className="text-3xl font-bold text-gray-900">{role === 'landlord' ? 'Landlord support' : 'Tenant support'}</h1>
                    </div>
                    <Link to={dashboardPath} className="btn btn-outline">
                        Back to Dashboard
                    </Link>
                </div>

                <div className="mt-6 grid gap-4 md:grid-cols-3">
                    <a href={`tel:${tenantSupportContacts.phone.replace(/\s+/g, '')}`} className="card p-5 hover:shadow-lg transition">
                        <HiPhone className="h-7 w-7 text-blue-600" />
                        <p className="mt-4 text-sm font-medium text-gray-500">Support number</p>
                        <p className="mt-1 text-lg font-semibold text-gray-900">{tenantSupportContacts.phone}</p>
                    </a>
                    <a href={`mailto:${tenantSupportContacts.email}`} className="card p-5 hover:shadow-lg transition">
                        <HiMail className="h-7 w-7 text-emerald-600" />
                        <p className="mt-4 text-sm font-medium text-gray-500">Email</p>
                        <p className="mt-1 text-lg font-semibold text-gray-900">{tenantSupportContacts.email}</p>
                    </a>
                    <Link to="/support-chat" className="card p-5 hover:shadow-lg transition">
                        <HiChatAlt2 className="h-7 w-7 text-purple-600" />
                        <p className="mt-4 text-sm font-medium text-gray-500">Chat</p>
                        <p className="mt-1 text-lg font-semibold text-gray-900">{tenantSupportContacts.chat}</p>
                    </Link>
                </div>

                <div className="card mt-6 p-6">
                    <div className="flex items-center gap-3">
                        <HiSupport className="h-6 w-6 text-blue-600" />
                        <h2 className="text-xl font-semibold text-gray-900">FAQ</h2>
                    </div>
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                        {faqs.map((item) => (
                            <div key={item.question} className="rounded-lg border border-gray-200 p-4">
                                <h3 className="text-sm font-semibold text-gray-900">{item.question}</h3>
                                <p className="mt-2 text-sm text-gray-600">{item.answer}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

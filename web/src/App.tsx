// src/App.tsx
import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './contexts/AuthContext'
import { useAuth } from './hooks/useAuth'
import { AppPopupProvider } from './contexts/AppPopupContext'
import HomePage from './pages/shared/HomePage'
import AboutPage from './pages/shared/about/AboutPage'
import LoginPage from './pages/shared/auth/LoginPage'
import RegisterPage from './pages/shared/auth/RegisterPage'
import ForgotPasswordPage from './pages/shared/auth/ForgotPasswordPage'
import ResetPasswordPage from './pages/shared/auth/ResetPasswordPage'
import RepresentativeKycPage from './pages/shared/RepresentativeKycPage'
import LandlordDashboardPage from './pages/landlord/LandlordDashboardPage'
import TenantDashboardPage from './pages/tenants/TenantDashboardPage'
import SearchPage from './pages/shared/SearchPage'
import LocationAnalyticsPage from './pages/shared/LocationAnalyticsPage'
import ListingDetailPage from './pages/shared/listings/ListingDetailPage'
import EnquiriesPage from './pages/tenants/TenantEnquiriesPage'
import ChatThreadPage from './pages/shared/messages/ChatThreadPage'
import TenantVerificationPage from './pages/tenants/TenantVerificationPage'
import ProfilePage from './pages/shared/profile/ProfilePage'
import FavouritesPage from './pages/tenants/FavouritesPage'
import PropertySearchRequirementPage from './pages/tenants/PropertySearchRequirementPage'
import RentPage from './pages/tenants/RentPage'
import RentalProgressPage from './pages/tenants/RentalProgressPage'
import ContactLandlordPage from './pages/tenants/ContactLandlordPage'
import LandlordEnquiriesPage from './pages/landlord/LandlordEnquiriesPage'
import LandlordVerificationPage from './pages/landlord/LandlordVerificationPage'
import TenancyAgreementPage from './pages/landlord/TenancyAgreementPage'
import PublicLandlordProfilePage from './pages/landlord/PublicLandlordProfilePage'
import PublicLandlordPropertiesPage from './pages/landlord/PublicLandlordPropertiesPage'
import PublicTenantProfilePage from './pages/tenants/PublicTenantProfilePage'
import TenantProfilePage from './pages/tenants/TenantProfilePage'
import BillingPage from './pages/shared/billing/BillingPage'
import SubscriptionPaymentPage from './pages/shared/billing/SubscriptionPaymentPage'
import ListingFormPage from './pages/landlord/ListingFormPage'
import NewListingPage from './pages/landlord/NewListingPage'
import FeaturedPropertiesPage from './pages/landlord/FeaturedPropertiesPage'
import FeaturedPropertyPaymentPage from './pages/landlord/FeaturedPropertyPaymentPage'
import SettingsPage from './pages/shared/settings/SettingsPage'
import FeedbackPage from './pages/shared/feedback/FeedbackPage'
import HowItWorksPage from './pages/shared/how-it-works/HowItWorksPage'
import LegalDocumentPage from './pages/shared/legal/LegalDocumentPage'
import TenantComplaintPage from './pages/tenants/TenantComplaintPage'
import TenantIssuesPage from './pages/tenants/TenantIssuesPage'
import TenantSupportPage from './pages/tenants/TenantSupportPage'
import SupportChatPage from './pages/shared/support/SupportChatPage'
import CommunityChatPage from './pages/shared/support/CommunityChatPage'
import AdminVerificationPage from './pages/shared/admin/AdminVerificationPage'
import AdminLoginPage from './pages/shared/admin/AdminLoginPage'
import AdminDashboardPage from './pages/shared/admin/AdminDashboardPage'
import AdminRegisterPage from './pages/shared/admin/AdminRegisterPage'
import AgentLandingPage from './pages/agents/AgentLandingPage'
import AgentRegistrationPage from './pages/agents/AgentRegistrationPage'
import AgentLoginPage from './pages/agents/AgentLoginPage'
import AgentAboutPage from './pages/agents/AgentAboutPage'
import AgentHowItWorksPage from './pages/agents/AgentHowItWorksPage'
import AgentDashboardPage from './pages/agents/AgentDashboardPage'
import AgentProfilePage from './pages/agents/AgentProfilePage'
import AgentVerificationPage from './pages/agents/AgentVerificationPage'
import AgentInspectionPage from './pages/agents/AgentInspectionPage'
import AgentChecklistPage from './pages/agents/AgentChecklistPage'
import AgentReferralsPage from './pages/agents/AgentReferralsPage'
import ServicePaymentPage from './pages/shared/payments/ServicePaymentPage'
import AdminRouteWrapper from './components/AdminRouteWrapper'
import ProtectedRoute from './components/ProtectedRoute'
import VerificationByRolePage from './components/VerificationByRolePage'

const queryClient = new QueryClient()

function ScrollToTop() {
    const { pathname } = useLocation()
    useEffect(() => {
        window.scrollTo(0, 0)
    }, [pathname])
    return null
}

function AccountFreezeGate({ children }: { children: React.ReactNode }) {
    const { user, isRestoring, logout } = useAuth()
    const location = useLocation()

    const isAccountManagementRoute = (
        location.pathname === '/dashboard/settings'
        || location.pathname === '/login'
        || location.pathname === '/register'
        || location.pathname === '/forgot-password'
        || location.pathname.startsWith('/reset-password/')
    )

    if (!isRestoring && user?.account_frozen && !isAccountManagementRoute) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-gray-50 px-6 py-12">
                <div className="card w-full max-w-lg p-8 text-center">
                    <p className="text-sm font-semibold uppercase tracking-[0.2em] text-blue-600">Account frozen</p>
                    <h1 className="mt-3 text-3xl font-bold text-gray-900">Your account is currently frozen</h1>
                    <p className="mt-4 text-gray-600">
                        Your data is safe, but listings, profiles and other RentDirect services are unavailable until you unfreeze your account.
                    </p>
                    <div className="mt-8 flex flex-wrap justify-center gap-3">
                        <Link to="/dashboard/settings" className="btn btn-primary">Open Account Settings</Link>
                        <button type="button" className="btn btn-outline" onClick={() => void logout()}>Log out</button>
                    </div>
                </div>
            </div>
        )
    }

    return <>{children}</>
}

function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <Router>
                <ScrollToTop />
                <AuthProvider>
                    <AppPopupProvider>
                        <AccountFreezeGate>
                            <AdminRouteWrapper>
                                <Routes>
                                    {/* Public Routes */}
                                    <Route path="/" element={<HomePage />} />
                                    <Route path="/about" element={<AboutPage />} />
                                    <Route path="/how-it-works" element={<HowItWorksPage />} />
                                    <Route path="/legal/:slug" element={<LegalDocumentPage />} />
                                    <Route path="/login" element={<LoginPage />} />
                                    <Route path="/register" element={<RegisterPage />} />
                                    <Route path="/agents" element={<AgentLandingPage />} />
                                    <Route path="/agents/register" element={<AgentRegistrationPage />} />
                                    <Route path="/agents/login" element={<AgentLoginPage />} />
                                    <Route path="/agents/about" element={<AgentAboutPage />} />
                                    <Route path="/agents/how-it-works" element={<AgentHowItWorksPage />} />
                                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                                    <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
                                    <Route path="/representative-kyc/:token" element={<RepresentativeKycPage />} />
                                    <Route path="/dashboard/landlord/:userId" element={<LandlordDashboardPage />} />
                                    <Route path="/dashboard/tenant/:userId" element={<TenantDashboardPage />} />
                                    <Route path="/search" element={<SearchPage />} />
                                    <Route path="/search/location-analytics" element={<LocationAnalyticsPage />} />
                                    <Route path="/listings/new" element={
                                        <ProtectedRoute requiredRoles={['landlord', 'admin']}>
                                            <NewListingPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/listings/new/:category" element={
                                        <ProtectedRoute requiredRoles={['landlord', 'admin']}>
                                            <ListingFormPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/listings/:id/edit" element={
                                        <ProtectedRoute requiredRoles={['landlord', 'admin']}>
                                            <ListingFormPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/listings/:id" element={<ListingDetailPage />} />
                                    <Route path="/enquiries" element={<EnquiriesPage />} />
                                    <Route path="/chat/:userId" element={<ChatThreadPage />} />
                                    <Route path="/verify" element={<VerificationByRolePage />} />
                                    <Route path="/profile/:userId" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'admin']}>
                                            <ProfilePage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/tenants/:tenantId/profile" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'admin']}>
                                            <TenantProfilePage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/tenants/:tenantId" element={<PublicTenantProfilePage />} />
                                    <Route path="/billing" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <BillingPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/billing/subscriptions/pay/:paymentId" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <SubscriptionPaymentPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/dashboard/settings" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'agent', 'admin']}>
                                            <SettingsPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/feedback" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'agent']}>
                                            <FeedbackPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/complaint" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <TenantComplaintPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/issues" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <TenantIssuesPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/support" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'agent']}>
                                            <TenantSupportPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/support-chat" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord', 'agent']}>
                                            <SupportChatPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/community-chat" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <CommunityChatPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/favourites" element={<FavouritesPage />} />
                                    <Route path="/search-requirement" element={
                                        <ProtectedRoute requiredRoles={['tenant']}>
                                            <PropertySearchRequirementPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/rent/:id" element={<RentPage />} />
                                    <Route path="/rental-progress/:bookingId" element={
                                        <ProtectedRoute requiredRoles={['tenant', 'landlord']}>
                                            <RentalProgressPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/contact-landlord/:id" element={<ContactLandlordPage />} />
                                    <Route path="/landlord/enquiries" element={<LandlordEnquiriesPage />} />
                                    <Route path="/landlord/verification" element={
                                        <ProtectedRoute requiredRoles={['landlord']}>
                                            <LandlordVerificationPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/landlord/tenancy-agreements/:bookingId" element={
                                        <ProtectedRoute requiredRoles={['landlord']}>
                                            <TenancyAgreementPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/tenant/tenancy-agreements/:bookingId" element={
                                        <ProtectedRoute requiredRoles={['tenant']}>
                                            <TenancyAgreementPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/dashboard" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentDashboardPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/profile" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentProfilePage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/verification" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentVerificationPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/checklist" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentChecklistPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/referrals" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentReferralsPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/agents/inspections/:inspectionId" element={
                                        <ProtectedRoute requiredRoles={['agent']}>
                                            <AgentInspectionPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/service-payments/:paymentId" element={
                                        <ProtectedRoute requiredRoles={['agent', 'landlord']}>
                                            <ServicePaymentPage />
                                        </ProtectedRoute>
                                    } />
                                    <Route path="/landlords/:landlordId/properties" element={<PublicLandlordPropertiesPage />} />
                                    <Route path="/landlords/:landlordId" element={<PublicLandlordProfilePage />} />
                                    <Route path="/dashboard/featured-properties" element={<FeaturedPropertiesPage />} />
                                    <Route path="/dashboard/featured-properties/pay/:paymentId" element={<FeaturedPropertyPaymentPage />} />

                                    {/* Admin Routes - No Public Navbar */}
                                    <Route path="/admin/login" element={<AdminLoginPage />} />
                                    <Route path="/admin/register" element={<AdminRegisterPage />} />
                                    <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
                                    <Route path="/admin/verification" element={<AdminVerificationPage />} />
                                </Routes>
                            </AdminRouteWrapper>
                        </AccountFreezeGate>
                    </AppPopupProvider>
                </AuthProvider>
            </Router>
        </QueryClientProvider>
    )
}

export default App

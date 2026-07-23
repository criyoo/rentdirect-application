import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAppPopup } from '@/contexts/AppPopupContext'
import { useAuth } from '@/hooks/useAuth'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { stateOfOriginOptions, validateMobile, validateNin, validateResidence } from '@/lib/profile'
import { User, UserResidence } from '@/types'

type VerificationProgress = {
    status?: string
}

type VerificationStatusResponse = {
    physical_property?: VerificationProgress
}

type EmergencyContactForm = {
    first_name: string
    middle_name: string
    last_name: string
    phone_number: string
    email: string
    relationship: string
    address: string
}

const emptyEmergencyContactForm: EmergencyContactForm = {
    first_name: '',
    middle_name: '',
    last_name: '',
    phone_number: '',
    email: '',
    relationship: '',
    address: '',
}

type SettingsOtpPurpose = 'profile' | 'password'

type SettingsOtpChallenge = {
    purpose: SettingsOtpPurpose
    targetEmail: string
}

type SettingsOtpRequestResponse = {
    purpose: SettingsOtpPurpose
    target_email: string
    expires_in_seconds: number
    message: string
}

function normalizeResidence(residence?: UserResidence | null): UserResidence {
    return {
        state: residence?.state || '',
        city: residence?.city || '',
        address: residence?.address || '',
        origin_country: residence?.origin_country || '',
        origin_city: residence?.origin_city || '',
    }
}

function asRecord(value: unknown): Record<string, any> {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        return value as Record<string, any>
    }
    return {}
}

function normalizeEmergencyContact(profile?: Record<string, any> | null): EmergencyContactForm {
    const emergencyContact = asRecord(asRecord(profile).emergency_contact)

    return {
        first_name: String(emergencyContact.first_name || ''),
        middle_name: String(emergencyContact.middle_name || ''),
        last_name: String(emergencyContact.last_name || ''),
        phone_number: String(emergencyContact.phone_number || ''),
        email: String(emergencyContact.email || ''),
        relationship: String(emergencyContact.relationship || ''),
        address: String(emergencyContact.address || ''),
    }
}

function buildEmergencyContactPayload(contact: EmergencyContactForm) {
    return {
        first_name: contact.first_name.trim(),
        middle_name: contact.middle_name.trim(),
        last_name: contact.last_name.trim(),
        phone_number: contact.phone_number.trim(),
        email: contact.email.trim(),
        relationship: contact.relationship.trim(),
        address: contact.address.trim(),
    }
}

function getVerificationStatusLabel(status?: string) {
    if (status === 'verified' || status === 'approved') {
        return 'Verified'
    }
    if (status === 'pending' || status === 'under_review') {
        return 'Pending'
    }
    if (status === 'rejected') {
        return 'Rejected'
    }
    return 'Not started'
}

function getVerificationStatusClassName(status?: string) {
    if (status === 'verified' || status === 'approved') {
        return 'text-green-600'
    }
    if (status === 'pending' || status === 'under_review') {
        return 'text-amber-600'
    }
    if (status === 'rejected') {
        return 'text-red-600'
    }
    return 'text-gray-500'
}

function extractErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }

    const detail = error?.response?.data?.detail
    if (detail) {
        return detail
    }

    const message = Object.values(error?.response?.data || {})
        .flat()
        .find(Boolean)

    return typeof message === 'string' ? message : error?.message || fallback
}

export default function SettingsPage() {
    const { user, logout } = useAuth()
    const { confirm } = useAppPopup()
    const qc = useQueryClient()
    const { data: me, isLoading, isError } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: verificationStatus } = useQuery({
        queryKey: ['verification', 'status', 'settings'],
        queryFn: async () => (await api.get<VerificationStatusResponse>('/landlord-verification-requests/status')).data,
        enabled: me?.role === 'landlord',
    })

    const [name, setName] = useState('')
    const [email, setEmail] = useState('')
    const [mobile, setMobile] = useState('')
    const [ninNumber, setNinNumber] = useState('')
    const [stateOfOrigin, setStateOfOrigin] = useState('')
    const [residence, setResidence] = useState<UserResidence>(normalizeResidence())
    const [emergencyContact, setEmergencyContact] = useState<EmergencyContactForm>(emptyEmergencyContactForm)
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

    const [newPassword, setNewPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [otpCode, setOtpCode] = useState('')
    const [otpChallenge, setOtpChallenge] = useState<SettingsOtpChallenge | null>(null)

    const [showDeleteModal, setShowDeleteModal] = useState(false)
    const [selectedFreezeDuration, setSelectedFreezeDuration] = useState<number | null>(null)
    const [accountFrozen, setAccountFrozen] = useState(false)

    const isIndividualLandlord = me?.role === 'landlord' && me.landlord_verification_type === 'individual'

    useEffect(() => {
        if (!me) return

        setName(me.name || '')
        setEmail(me.email || '')
        setMobile(me.mobile || '')
        setNinNumber(me.nin_number || '')
        setStateOfOrigin(me.state_of_origin || '')
        setResidence(normalizeResidence(me.residence))
        setEmergencyContact(
            me.role === 'landlord' && me.landlord_verification_type === 'individual'
                ? normalizeEmergencyContact(me.landlord_verification_profile)
                : emptyEmergencyContactForm,
        )
    }, [me])

    useEffect(() => {
        const freezeInfo = localStorage.getItem('account_freeze')
        if (!freezeInfo) {
            return
        }

        try {
            const parsed = JSON.parse(freezeInfo)
            const startDate = new Date(parsed.start_date)
            const endDate = new Date(startDate)
            endDate.setMonth(endDate.getMonth() + parsed.duration_months)

            if (new Date() < endDate) {
                setAccountFrozen(true)
            } else {
                localStorage.removeItem('account_freeze')
            }
        } catch {
            localStorage.removeItem('account_freeze')
        }
    }, [])

    const validateProfile = (): boolean => {
        const nextErrors: Record<string, string> = {}

        const mobileError = validateMobile(mobile)
        if (mobileError) nextErrors.mobile = mobileError

        const ninError = validateNin(ninNumber)
        if (ninError) nextErrors.nin_number = ninError

        if (isIndividualLandlord) {
            const emergencyPhoneError = validateMobile(emergencyContact.phone_number)
            if (emergencyPhoneError) nextErrors.emergency_phone_number = emergencyPhoneError
        }

        Object.assign(nextErrors, validateResidence(stateOfOrigin, residence))

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const buildProfilePayload = (): Record<string, any> => {
        const payload: Record<string, any> = {
            name: name.trim(),
            email: email.trim(),
            mobile: mobile.trim(),
            nin_number: ninNumber.trim(),
            state_of_origin: stateOfOrigin,
            residence: {
                state: residence.state?.trim() || '',
                city: residence.city?.trim() || '',
                address: residence.address?.trim() || '',
                origin_country: stateOfOrigin === 'Others' ? residence.origin_country?.trim() || '' : '',
                origin_city: stateOfOrigin === 'Others' ? residence.origin_city?.trim() || '' : '',
            },
        }

        if (isIndividualLandlord) {
            const currentProfile = asRecord(me?.landlord_verification_profile)
            payload.landlord_verification_profile = {
                ...currentProfile,
                email: email.trim(),
                contact_number: mobile.trim(),
                emergency_contact: {
                    ...asRecord(currentProfile.emergency_contact),
                    ...buildEmergencyContactPayload(emergencyContact),
                },
            }
        }

        return payload
    }

    const closeOtpChallenge = () => {
        setOtpChallenge(null)
        setOtpCode('')
    }

    const requestSettingsOtp = useMutation({
        mutationFn: async ({ purpose, targetEmail }: SettingsOtpChallenge) => {
            return (await api.post<SettingsOtpRequestResponse>('/users/me/settings/request-otp', {
                purpose,
                target_email: targetEmail,
            })).data
        },
        onSuccess: (response) => {
            setOtpCode('')
            setOtpChallenge({
                purpose: response.purpose,
                targetEmail: response.target_email,
            })
            alert(`Verification code sent to ${response.target_email}.`)
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to send a verification code.'))
        },
    })

    const saveProfile = useMutation({
        mutationFn: async (code: string) => {
            if (!validateProfile()) {
                throw new Error('Please fix the highlighted fields before saving.')
            }

            const payload = buildProfilePayload()
            return (await api.post<User>('/users/me/settings', {
                ...payload,
                otp_code: code,
            })).data
        },
        onSuccess: (nextUser) => {
            qc.setQueryData(['users', 'me'], nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            closeOtpChallenge()
            alert('Settings updated successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to update your settings.'))
        },
    })

    const changePassword = useMutation({
        mutationFn: async (code: string) => {
            if (!newPassword || !confirmPassword) {
                throw new Error('Fill in all password fields.')
            }
            if (newPassword !== confirmPassword) {
                throw new Error('New password and confirmation must match.')
            }

            await api.post('/users/me/password', {
                new_password: newPassword,
                otp_code: code,
            })
        },
        onSuccess: () => {
            setNewPassword('')
            setConfirmPassword('')
            closeOtpChallenge()
            alert('Password updated successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to update your password.'))
        },
    })

    const freezeAccount = useMutation({
        mutationFn: async (duration: number) => {
            const response = await api.post('/users/me/freeze', { duration_months: duration })
            localStorage.setItem('account_freeze', JSON.stringify({
                duration_months: duration,
                start_date: new Date().toISOString(),
                monthly_fee_percentage: 10,
                frozen_until: response.data.frozen_until,
            }))
            return response.data
        },
        onSuccess: () => {
            alert('Account frozen successfully! You will be charged 10% of the subscription fee monthly.')
            setAccountFrozen(true)
            setSelectedFreezeDuration(null)
            setShowDeleteModal(false)
        },
        onError: (error) => {
            alert('Failed to freeze account: ' + extractErrorMessage(error, 'Freeze failed'))
        },
    })

    const deleteAccount = useMutation({
        mutationFn: async () => {
            await api.delete('/users/me')
        },
        onSuccess: async () => {
            localStorage.removeItem('account_freeze')
            setShowDeleteModal(false)
            await logout()
        },
        onError: (error) => {
            alert('Failed to delete account: ' + extractErrorMessage(error, 'Delete failed'))
        },
    })

    const dashboardPath = user?.role === 'landlord'
        ? `/dashboard/landlord/${user.id}`
        : user?.role === 'tenant'
            ? `/dashboard/tenant/${user.id}`
            : '/'

    const beginProfileVerification = () => {
        if (!me) {
            return
        }
        if (!validateProfile()) {
            return
        }

        requestSettingsOtp.mutate({
            purpose: 'profile',
            targetEmail: email.trim().toLowerCase() || me.email,
        })
    }

    const beginPasswordVerification = () => {
        if (!me) {
            return
        }
        if (!newPassword || !confirmPassword) {
            alert('Fill in all password fields.')
            return
        }
        if (newPassword !== confirmPassword) {
            alert('New password and confirmation must match.')
            return
        }

        requestSettingsOtp.mutate({
            purpose: 'password',
            targetEmail: me.email,
        })
    }

    const confirmOtpChallenge = () => {
        const normalizedCode = otpCode.trim().toUpperCase()
        if (!normalizedCode || !otpChallenge) {
            alert('Enter the verification code sent to your email.')
            return
        }

        if (otpChallenge.purpose === 'profile') {
            saveProfile.mutate(normalizedCode)
            return
        }

        changePassword.mutate(normalizedCode)
    }

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6 text-gray-600">Loading settings...</div>
            </div>
        )
    }

    if (isError || !me) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6">
                    <h1 className="text-2xl font-bold text-gray-900">Unable to load settings</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page or sign in again.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="mb-5">
                <DashboardBackButton fallbackTo={dashboardPath} />
            </div>
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Dashboard Settings</p>
                    <h1 className="text-3xl font-bold text-gray-900">Manage your account</h1>
                    <p className="mt-2 text-gray-600">
                        Update your profile details, contact information, address, and password from one place.
                    </p>
                </div>
                <div className="flex flex-wrap gap-3">
                    <Link to={dashboardPath} className="btn btn-outline">
                        Back to Dashboard
                    </Link>
                    <Link to={`/profile/${me.id}`} className="btn btn-primary">
                        Open Profile Page
                    </Link>
                </div>
            </div>

            <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
                <section className="card p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Profile details</h2>
                        <p className="mt-2 text-sm text-gray-600">Keep your landlord or tenant account information current.</p>
                    </div>

                    <div className="grid gap-5 md:grid-cols-2">
                        <div>
                            <label className="form-label">Full name</label>
                            <input className="form-input" value={name} onChange={e => setName(e.target.value)} placeholder="Enter your full name" />
                        </div>
                        <div>
                            <label className="form-label">NIN number</label>
                            <input className="form-input" value={ninNumber} onChange={e => setNinNumber(e.target.value)} placeholder="Optional 11-digit NIN" />
                            {fieldErrors.nin_number && <p className="form-error">{fieldErrors.nin_number}</p>}
                        </div>
                    </div>

                    <div className="mt-6 grid gap-5 md:grid-cols-2">
                        <div>
                            <label className="form-label">State of origin</label>
                            <select className="form-input" value={stateOfOrigin} onChange={e => setStateOfOrigin(e.target.value)}>
                                <option value="">Select state of origin</option>
                                {stateOfOriginOptions.map(option => (
                                    <option key={option} value={option}>{option}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="mt-6 rounded-xl border border-gray-200 p-5">
                        <div className="mb-4">
                            <h3 className="text-lg font-semibold text-gray-900">Contact settings</h3>
                            <p className="mt-1 text-sm text-gray-600">Update the account contact details used for alerts, sign-in, and verification.</p>
                        </div>

                        <div className="grid gap-5 md:grid-cols-2">
                            <div>
                                <label className="form-label">Change email</label>
                                <input className="form-input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Enter your email" />
                            </div>
                            <div>
                                <label className="form-label">Change Phone Number</label>
                                <input className="form-input" value={mobile} onChange={e => setMobile(e.target.value)} placeholder="08012345678 or +2348012345678" />
                                {fieldErrors.mobile && <p className="form-error">{fieldErrors.mobile}</p>}
                            </div>
                        </div>
                    </div>

                    {isIndividualLandlord && (
                        <div className="mt-6 rounded-xl border border-gray-200 p-5">
                            <div className="mb-4">
                                <h3 className="text-lg font-semibold text-gray-900">Change Emergency contact details</h3>
                                <p className="mt-1 text-sm text-gray-600">Keep a reachable emergency contact on file for your landlord account.</p>
                            </div>

                            <div className="grid gap-5 md:grid-cols-3">
                                <div>
                                    <label className="form-label">First name</label>
                                    <input
                                        className="form-input"
                                        value={emergencyContact.first_name}
                                        onChange={e => setEmergencyContact(current => ({ ...current, first_name: e.target.value }))}
                                        placeholder="First name"
                                    />
                                </div>
                                <div>
                                    <label className="form-label">Middle name</label>
                                    <input
                                        className="form-input"
                                        value={emergencyContact.middle_name}
                                        onChange={e => setEmergencyContact(current => ({ ...current, middle_name: e.target.value }))}
                                        placeholder="Middle name"
                                    />
                                </div>
                                <div>
                                    <label className="form-label">Last name</label>
                                    <input
                                        className="form-input"
                                        value={emergencyContact.last_name}
                                        onChange={e => setEmergencyContact(current => ({ ...current, last_name: e.target.value }))}
                                        placeholder="Last name"
                                    />
                                </div>
                            </div>

                            <div className="mt-5 grid gap-5 md:grid-cols-3">
                                <div>
                                    <label className="form-label">Phone number</label>
                                    <input
                                        className="form-input"
                                        value={emergencyContact.phone_number}
                                        onChange={e => setEmergencyContact(current => ({ ...current, phone_number: e.target.value }))}
                                        placeholder="08012345678 or +2348012345678"
                                    />
                                    {fieldErrors.emergency_phone_number && <p className="form-error">{fieldErrors.emergency_phone_number}</p>}
                                </div>
                                <div>
                                    <label className="form-label">Email</label>
                                    <input
                                        className="form-input"
                                        type="email"
                                        value={emergencyContact.email}
                                        onChange={e => setEmergencyContact(current => ({ ...current, email: e.target.value }))}
                                        placeholder="Emergency contact email"
                                    />
                                </div>
                                <div>
                                    <label className="form-label">Relationship</label>
                                    <input
                                        className="form-input"
                                        value={emergencyContact.relationship}
                                        onChange={e => setEmergencyContact(current => ({ ...current, relationship: e.target.value }))}
                                        placeholder="Relationship"
                                    />
                                </div>
                            </div>

                            <div className="mt-5">
                                <label className="form-label">Address</label>
                                <textarea
                                    className="form-input min-h-28"
                                    value={emergencyContact.address}
                                    onChange={e => setEmergencyContact(current => ({ ...current, address: e.target.value }))}
                                    placeholder="Emergency contact address"
                                />
                            </div>
                        </div>
                    )}

                    {stateOfOrigin === 'Others' && (
                        <div className="mt-6 grid gap-5 md:grid-cols-2">
                            <div>
                                <label className="form-label">Country of origin</label>
                                <input
                                    className="form-input"
                                    value={residence.origin_country || ''}
                                    onChange={e => setResidence(current => ({ ...current, origin_country: e.target.value }))}
                                    placeholder="Enter country of origin"
                                />
                                {fieldErrors.origin_country && <p className="form-error">{fieldErrors.origin_country}</p>}
                            </div>
                            <div>
                                <label className="form-label">City of origin</label>
                                <input
                                    className="form-input"
                                    value={residence.origin_city || ''}
                                    onChange={e => setResidence(current => ({ ...current, origin_city: e.target.value }))}
                                    placeholder="Enter city of origin"
                                />
                                {fieldErrors.origin_city && <p className="form-error">{fieldErrors.origin_city}</p>}
                            </div>
                        </div>
                    )}

                    <div className="mt-6 rounded-xl border border-gray-200 p-5">
                        <div className="mb-4">
                            <h3 className="text-lg font-semibold text-gray-900">Address information</h3>
                            <p className="mt-1 text-sm text-gray-600">Use your current residential address for applications and landlord communication.</p>
                        </div>

                        <div className="grid gap-5 md:grid-cols-2">
                            <div>
                                <label className="form-label">Residence state</label>
                                <input
                                    className="form-input"
                                    value={residence.state || ''}
                                    onChange={e => setResidence(current => ({ ...current, state: e.target.value }))}
                                    placeholder="Enter residence state"
                                />
                            </div>
                            <div>
                                <label className="form-label">Residence city</label>
                                <input
                                    className="form-input"
                                    value={residence.city || ''}
                                    onChange={e => setResidence(current => ({ ...current, city: e.target.value }))}
                                    placeholder="Enter residence city"
                                />
                            </div>
                        </div>

                        <div className="mt-5">
                            <label className="form-label">Street address</label>
                            <textarea
                                className="form-input min-h-28"
                                value={residence.address || ''}
                                onChange={e => setResidence(current => ({ ...current, address: e.target.value }))}
                                placeholder="Enter your full address"
                            />
                            {fieldErrors.residence && <p className="form-error">{fieldErrors.residence}</p>}
                        </div>
                    </div>

                    <div className="mt-6 flex justify-end">
                        <button
                            className="btn btn-primary px-6 py-3"
                            onClick={beginProfileVerification}
                            disabled={requestSettingsOtp.isPending || saveProfile.isPending}
                        >
                            {requestSettingsOtp.isPending || saveProfile.isPending ? 'Processing...' : 'Save Settings'}
                        </button>
                    </div>
                </section>

                <div className="space-y-6">
                    <section className="card p-6">
                        <div className="mb-6">
                            <h2 className="text-2xl font-bold text-gray-900">Password</h2>
                            <p className="mt-2 text-sm text-gray-600">Change your password with an OTP sent to your registered email.</p>
                        </div>

                        <div className="space-y-5">
                            <div>
                                <label className="form-label">New password</label>
                                <input
                                    className="form-input"
                                    type="password"
                                    value={newPassword}
                                    onChange={e => setNewPassword(e.target.value)}
                                    placeholder="Enter new password"
                                />
                            </div>
                            <div>
                                <label className="form-label">Confirm new password</label>
                                <input
                                    className="form-input"
                                    type="password"
                                    value={confirmPassword}
                                    onChange={e => setConfirmPassword(e.target.value)}
                                    placeholder="Confirm new password"
                                />
                            </div>

                            <button
                                className="btn btn-primary w-full py-3"
                                onClick={beginPasswordVerification}
                                disabled={requestSettingsOtp.isPending || changePassword.isPending}
                            >
                                {requestSettingsOtp.isPending || changePassword.isPending ? 'Processing...' : 'Update Password'}
                            </button>
                        </div>
                    </section>

                    <section className="card p-6">
                        <h2 className="text-2xl font-bold text-gray-900">Account snapshot</h2>
                        <div className="mt-5 space-y-4 text-sm text-gray-600">
                            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                                <span>Account type</span>
                                <span className="font-semibold capitalize text-gray-900">{me.role}</span>
                            </div>
                            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                                <span>Email verification</span>
                                <span className={`font-semibold ${me.email_verified ? 'text-green-600' : 'text-amber-600'}`}>
                                    {me.email_verified ? 'Verified' : 'Pending'}
                                </span>
                            </div>
                            <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                                <span>Identity verification</span>
                                <span className={`font-semibold ${me.is_verified ? 'text-green-600' : 'text-amber-600'}`}>
                                    {me.is_verified ? 'Verified' : 'Awaiting review'}
                                </span>
                            </div>
                            {me.role === 'landlord' && (
                                <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                                    <span>Physical House Verification</span>
                                    <span className={`font-semibold ${getVerificationStatusClassName(verificationStatus?.physical_property?.status)}`}>
                                        {getVerificationStatusLabel(verificationStatus?.physical_property?.status)}
                                    </span>
                                </div>
                            )}
                        </div>
                    </section>

                    <section className="card p-6">
                        <div className="mb-4">
                            <h2 className="text-2xl font-bold text-gray-900">Delete Account</h2>
                            <p className="mt-2 text-sm text-gray-600">
                                Remove this account permanently, or freeze it temporarily instead.
                            </p>
                        </div>

                        {accountFrozen && (
                            <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <h3 className="text-sm font-medium text-blue-800">Account Frozen</h3>
                                        <p className="mt-1 text-sm text-blue-700">Your account is currently frozen. You&apos;re paying 10% of the subscription fee monthly.</p>
                                    </div>
                                    <button
                                        onClick={async () => {
                                            if (await confirm('Are you sure you want to unfreeze your account? You will be charged the full subscription fee.')) {
                                                localStorage.removeItem('account_freeze')
                                                setAccountFrozen(false)
                                                alert('Account unfrozen successfully!')
                                            }
                                        }}
                                        className="rounded-md bg-blue-100 px-3 py-2 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-200"
                                    >
                                        Unfreeze
                                    </button>
                                </div>
                            </div>
                        )}

                        <button
                            className="btn btn-danger w-full py-3"
                            onClick={() => setShowDeleteModal(true)}
                            disabled={deleteAccount.isPending || freezeAccount.isPending}
                        >
                            {deleteAccount.isPending ? 'Deleting...' : 'Delete Account'}
                        </button>
                    </section>
                </div>
            </div>

            {otpChallenge && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                    <div className="mx-4 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
                        <div className="mb-4">
                            <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">OTP Verification</p>
                            <h3 className="mt-2 text-2xl font-bold text-gray-900">
                                {otpChallenge.purpose === 'profile' ? 'Confirm settings update' : 'Confirm password change'}
                            </h3>
                            <p className="mt-2 text-sm text-gray-600">
                                Enter the verification code sent to <span className="font-semibold text-gray-900">{otpChallenge.targetEmail}</span>.
                            </p>
                        </div>

                        <div>
                            <label className="form-label">Verification code</label>
                            <input
                                className="form-input"
                                value={otpCode}
                                onChange={e => setOtpCode(e.target.value.toUpperCase())}
                                placeholder="Enter the 6-character code"
                                maxLength={6}
                            />
                        </div>

                        <div className="mt-6 flex flex-wrap justify-end gap-3">
                            <button
                                type="button"
                                className="btn btn-outline"
                                onClick={closeOtpChallenge}
                                disabled={requestSettingsOtp.isPending || saveProfile.isPending || changePassword.isPending}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => requestSettingsOtp.mutate(otpChallenge)}
                                disabled={requestSettingsOtp.isPending || saveProfile.isPending || changePassword.isPending}
                            >
                                {requestSettingsOtp.isPending ? 'Sending...' : 'Resend OTP'}
                            </button>
                            <button
                                type="button"
                                className="btn btn-primary"
                                onClick={confirmOtpChallenge}
                                disabled={requestSettingsOtp.isPending || saveProfile.isPending || changePassword.isPending}
                            >
                                {saveProfile.isPending || changePassword.isPending ? 'Verifying...' : 'Confirm'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showDeleteModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                    <div className="mx-4 w-full max-w-md rounded-lg bg-white p-6">
                        <div className="mb-4 flex items-center">
                            <div className="mx-auto flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-red-100">
                                <svg className="h-6 w-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
                                </svg>
                            </div>
                        </div>

                        <h3 className="mb-2 text-center text-lg font-medium text-gray-900">
                            Delete Account Warning
                        </h3>

                        <p className="mb-6 text-center text-sm text-gray-600">
                            Are you sure you want to delete your account? This action cannot be undone.
                        </p>

                        <div className="mb-6">
                            <h4 className="mb-3 text-sm font-medium text-gray-900">
                                Consider freezing your account instead:
                            </h4>
                            <div className="space-y-2">
                                {[3, 6, 12].map((duration) => (
                                    <label key={duration} className="flex cursor-pointer items-center rounded-lg border p-3 hover:bg-gray-50">
                                        <input
                                            type="radio"
                                            name="freezeDuration"
                                            value={duration}
                                            checked={selectedFreezeDuration === duration}
                                            onChange={() => setSelectedFreezeDuration(duration)}
                                            className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
                                        />
                                        <div className="ml-3">
                                            <span className="text-sm font-medium text-gray-900">{duration} months</span>
                                            <p className="text-xs text-gray-500">Pay 10% of subscription fee monthly</p>
                                        </div>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div className="flex gap-3">
                            <button
                                onClick={() => {
                                    setShowDeleteModal(false)
                                    setSelectedFreezeDuration(null)
                                }}
                                className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-gray-700 transition-colors hover:bg-gray-50"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    if (selectedFreezeDuration) {
                                        freezeAccount.mutate(selectedFreezeDuration)
                                    }
                                }}
                                disabled={!selectedFreezeDuration || freezeAccount.isPending}
                                className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                            >
                                {freezeAccount.isPending ? 'Freezing...' : 'Freeze Instead'}
                            </button>
                            <button
                                onClick={() => deleteAccount.mutate()}
                                disabled={deleteAccount.isPending}
                                className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:bg-gray-300"
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

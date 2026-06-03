/**
 * Photo Editing UI Component (React)
 * 
 * Features:
 * - Upload portrait photo
 * - Face detection validation
 * - Progress tracking
 * - Before/After preview
 * - Payment flow
 * - Download result
 */

import React, { useState } from 'react';

interface PhotoUploadProps {
  onSuccess?: (jobId: string) => void;
  onError?: (error: string) => void;
  context?: 'cv' | 'profile' | 'linkedin' | 'headshot';
  maxFileSize?: number; // bytes
}

interface JobStatus {
  job_id: string;
  status: 'queued' | 'processing' | 'done' | 'failed';
  progress: number;
  preview_url?: string;
  variants: Array<{
    index: number;
    preview_url?: string;
    download_url?: string;
  }>;
  confirmed: boolean;
  cost_actual_usd?: number;
  cost_estimate_usd?: number;
}

const PhotoUploadComponent: React.FC<PhotoUploadProps> = ({
  onSuccess,
  onError,
  context = 'cv',
  maxFileSize = 8 * 1024 * 1024, // 8MB default
}) => {
  const [file, setFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [selectedVariant, setSelectedVariant] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
  const token = localStorage.getItem('auth_token');

  // Handle file selection
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    // Validate format
    if (!['image/jpeg', 'image/png'].includes(selectedFile.type)) {
      setError('Only JPEG and PNG images are supported');
      return;
    }

    // Validate size
    if (selectedFile.size > maxFileSize) {
      setError(`File too large. Maximum size: ${(maxFileSize / 1024 / 1024).toFixed(0)}MB`);
      return;
    }

    setFile(selectedFile);
    setError(null);
  };

  // Upload and create job
  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file');
      return;
    }

    if (!consentConfirmed) {
      setError('Please confirm data handling policy');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('context', context);
      formData.append('variants', '2'); // Generate 2 variants
      formData.append('consent_confirmed', 'true');

      const response = await fetch(`${API_BASE_URL}/api/photo/upload`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.detail?.error || errorData.detail || 'Upload failed'
        );
      }

      const data = await response.json();
      setJobId(data.job_id);
      onSuccess?.(data.job_id);

      // Start polling status
      pollJobStatus(data.job_id);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Upload failed';
      setError(errorMsg);
      onError?.(errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

  // Poll job status
  const pollJobStatus = async (jid: string) => {
    const maxAttempts = 120; // 2 minutes with 1s interval
    let attempts = 0;

    const interval = setInterval(async () => {
      attempts++;

      try {
        const response = await fetch(`${API_BASE_URL}/api/photo/status/${jid}`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (!response.ok) throw new Error('Status fetch failed');

        const status: JobStatus = await response.json();
        setJobStatus(status);

        // Stop polling when done or failed
        if (status.status === 'done' || status.status === 'failed') {
          clearInterval(interval);
        }
      } catch (err) {
        console.error('Poll error:', err);
      }

      if (attempts >= maxAttempts) {
        clearInterval(interval);
        setError('Request timed out');
      }
    }, 1000);
  };

  // Confirm download
  const handleConfirm = async () => {
    if (!jobId) return;

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/photo/confirm/${jobId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ variant_index: selectedVariant }),
      });

      if (!response.ok) {
        throw new Error('Confirmation failed');
      }

      const result = await response.json();

      // Redirect to download or open in new tab
      window.location.href = result.download_url;

      // Update status
      setJobStatus((prev) => (prev ? { ...prev, confirmed: true } : null));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirmation failed');
    } finally {
      setIsLoading(false);
    }
  };

  // Render upload form
  if (!jobId) {
    return (
      <div className="photo-upload-container">
        <h2>Enhance Your Portrait Photo</h2>
        <p>Upload a professional portrait for CV, LinkedIn, or profile photo.</p>

        {error && <div className="error-message">{error}</div>}

        <div className="upload-area">
          <input
            type="file"
            accept="image/jpeg,image/png"
            onChange={handleFileChange}
            disabled={isLoading}
          />
          {file && <p>Selected: {file.name}</p>}
        </div>

        <div className="consent">
          <label>
            <input
              type="checkbox"
              checked={consentConfirmed}
              onChange={(e) => setConsentConfirmed(e.target.checked)}
            />
            I confirm data will be stored for 30 days and can be deleted anytime.
          </label>
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || !consentConfirmed || isLoading}
          className="upload-button"
        >
          {isLoading ? 'Uploading...' : 'Upload & Enhance'}
        </button>
      </div>
    );
  }

  // Render progress/results
  if (!jobStatus) {
    return <div className="loading">Loading...</div>;
  }

  return (
    <div className="photo-result-container">
      <h2>Enhancement Results</h2>

      {jobStatus.status === 'processing' && (
        <div className="progress-section">
          <p>Processing... {jobStatus.progress}%</p>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${jobStatus.progress}%` }}
            />
          </div>
          <p>{jobStatus.message}</p>
        </div>
      )}

      {jobStatus.status === 'failed' && (
        <div className="error-message">{jobStatus.message || 'Processing failed'}</div>
      )}

      {jobStatus.status === 'done' && (
        <div className="results-section">
          <p>Estimated Cost: ${jobStatus.cost_estimate_usd?.toFixed(2)}</p>

          {/* Variant selector */}
          <div className="variants">
            {jobStatus.variants.map((variant, idx) => (
              <div
                key={idx}
                className={`variant-item ${selectedVariant === idx ? 'selected' : ''}`}
                onClick={() => setSelectedVariant(idx)}
              >
                <img
                  src={variant.preview_url}
                  alt={`Variant ${idx + 1}`}
                  style={{ maxWidth: '200px' }}
                />
                <p>Variant {idx + 1}</p>
              </div>
            ))}
          </div>

          {/* Confirm button */}
          {!jobStatus.confirmed && (
            <button
              onClick={handleConfirm}
              disabled={isLoading}
              className="confirm-button"
            >
              {isLoading ? 'Processing...' : 'Confirm & Download'}
            </button>
          )}

          {jobStatus.confirmed && (
            <div className="success-message">
              ✓ Download link sent. Cost charged: ${jobStatus.cost_actual_usd?.toFixed(2)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PhotoUploadComponent;

-- Private CV bucket (design doc §3). No storage.objects policies are created,
-- so only the service role can read or write; users get 15-minute signed URLs
-- issued by FastAPI.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cvs',
  'cvs',
  false,
  10485760, -- 10 MB
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ]
);

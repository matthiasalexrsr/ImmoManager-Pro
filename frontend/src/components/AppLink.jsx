import { Link, useInRouterContext } from 'react-router-dom';

// An in-app link: inside the app it navigates without reloading (open forms and filters stay),
// outside a router (isolated component tests) it is a plain link.
export default function AppLink({ to, ...props }) {
  return useInRouterContext() ? <Link to={to} {...props} /> : <a href={to} {...props} />;
}
